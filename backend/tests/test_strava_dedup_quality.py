from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import strava as strava_service


class _DedupQuery:
    def __init__(self, db: "_DedupDb", table_name: str):
        self.db = db
        self.table_name = table_name
        self._update_payload: dict | None = None
        self._single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def update(self, payload: dict):
        self._update_payload = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            assert self.table_name == "workouts"
            self.db.workout_updates.append(dict(self._update_payload))
            self.db.workout.update(self._update_payload)
            return SimpleNamespace(data=[dict(self.db.workout)])
        if self.table_name == "athletes":
            return SimpleNamespace(data=dict(self.db.athlete))
        if self.table_name == "workouts":
            row = dict(self.db.workout)
            return SimpleNamespace(data=row if self._single else [row])
        raise AssertionError(f"unexpected table {self.table_name}")


class _DedupDb:
    def __init__(self, workout: dict):
        self.athlete = {
            "id": "athlete-1",
            "max_hr": 190,
            "resting_hr": 50,
            "threshold_hr": 170,
            "threshold_hr_source": "manual",
        }
        self.workout = workout
        self.workout_updates: list[dict] = []

    def table(self, name: str):
        return _DedupQuery(self, name)


def _activity(activity_id: int, **overrides) -> dict:
    base = {
        "id": activity_id,
        "sport_type": "Ride",
        "type": "Ride",
        "start_date": "2026-05-20T10:00:00Z",
        "elapsed_time": 3600,
        "name": f"Ride {activity_id}",
        "distance": 20_000,
    }
    base.update(overrides)
    return base


def _workout(**overrides) -> dict:
    base = {
        "id": "workout-1",
        "athlete_id": "athlete-1",
        "source": "strava",
        "sport": "bike",
        "strava_activity_id": 111,
        "strava_streams_fetched": True,
        "tss": 40,
        "source_ids": {"strava": ["111", "222"]},
        "raw_strava_payload": _activity(111, average_heartrate=145),
    }
    base.update(overrides)
    return base


def test_strava_alias_is_not_primary():
    workout = _workout(source_ids={"strava": ["111", "222", "bad-id"]})

    assert strava_service._strava_activity_is_primary(workout, 111)
    assert not strava_service._strava_activity_is_primary(workout, 222)
    assert strava_service._strava_activity_is_linked(workout, 222)
    assert not strava_service._strava_activity_is_linked(workout, 333)


def test_strava_detail_quality_prefers_stream_rich_payloads():
    sparse = strava_service._strava_detail_quality_score(
        _activity(111, average_heartrate=145),
        {},
        [],
    )
    rich = strava_service._strava_detail_quality_score(
        _activity(222, average_heartrate=145, weighted_average_watts=230),
        {
            "heartrate": {"data": [140] * 1200},
            "watts": {"data": [220] * 1200},
            "latlng": {"data": [[40.0, -75.0]] * 1200},
        },
        [{"distance": 1000, "elapsed_time": 180, "average_watts": 220}],
    )

    assert rich > sparse


def test_ingest_strava_duplicate_keeps_existing_when_candidate_is_worse(monkeypatch):
    db = _DedupDb(_workout())
    candidate = _activity(222)
    existing_streams = {"heartrate": {"data": [145] * 1200}}

    async def _fake_find_or_create(**_kwargs):
        return dict(db.workout), False

    async def _run():
        process = AsyncMock()
        monkeypatch.setattr(strava_service, "find_or_create_canonical_workout", _fake_find_or_create)
        monkeypatch.setattr(strava_service, "get_activity", AsyncMock(return_value=candidate))
        monkeypatch.setattr(strava_service, "get_activity_streams", AsyncMock(return_value={}))
        monkeypatch.setattr(strava_service, "get_activity_laps", AsyncMock(return_value=[]))
        monkeypatch.setattr(strava_service, "_load_stored_streams_dict", lambda *_args: existing_streams)
        monkeypatch.setattr(strava_service, "_load_cached_laps_for_workout", lambda *_args: [])
        monkeypatch.setattr(strava_service, "_upsert_activity_streams", lambda *_args: None)
        monkeypatch.setattr(strava_service, "_persist_activity_laps", lambda *_args: None)
        monkeypatch.setattr(strava_service, "process_and_save_workout", process)

        result = await strava_service.ingest_strava_activity(
            owner_strava_id=999,
            activity_id=222,
            db=db,
            access_token="token",
            athlete_id="athlete-1",
        )

        assert result["strava_activity_id"] == 111
        assert db.workout_updates == []
        process.assert_not_awaited()

    asyncio.run(_run())


def test_ingest_strava_duplicate_promotes_richer_candidate(monkeypatch):
    db = _DedupDb(_workout(raw_strava_payload=_activity(111), tss=None))
    candidate = _activity(222, average_heartrate=145, weighted_average_watts=230)
    candidate_streams = {
        "heartrate": {"data": [145] * 1200},
        "watts": {"data": [230] * 1200},
    }
    candidate_laps = [{"distance": 1000, "elapsed_time": 180, "average_watts": 230}]
    persisted: dict[str, object] = {}

    async def _fake_find_or_create(**_kwargs):
        return dict(db.workout), False

    async def _run():
        process = AsyncMock()
        monkeypatch.setattr(strava_service, "find_or_create_canonical_workout", _fake_find_or_create)
        monkeypatch.setattr(strava_service, "get_activity", AsyncMock(return_value=candidate))
        monkeypatch.setattr(strava_service, "get_activity_streams", AsyncMock(return_value=candidate_streams))
        monkeypatch.setattr(strava_service, "get_activity_laps", AsyncMock(return_value=candidate_laps))
        monkeypatch.setattr(strava_service, "_load_stored_streams_dict", lambda *_args: {})
        monkeypatch.setattr(strava_service, "_load_cached_laps_for_workout", lambda *_args: [])
        monkeypatch.setattr(
            strava_service,
            "_upsert_activity_streams",
            lambda _db, _wid, _aid, streams: persisted.setdefault("streams", streams),
        )
        monkeypatch.setattr(
            strava_service,
            "_persist_activity_laps",
            lambda _db, _wid, _aid, laps: persisted.setdefault("laps", laps),
        )
        monkeypatch.setattr(strava_service, "process_and_save_workout", process)

        result = await strava_service.ingest_strava_activity(
            owner_strava_id=999,
            activity_id=222,
            db=db,
            access_token="token",
            athlete_id="athlete-1",
        )

        assert result["strava_activity_id"] == 222
        assert db.workout_updates[-1]["strava_activity_id"] == 222
        assert db.workout_updates[-1]["raw_strava_payload"] == candidate
        assert persisted["streams"] == candidate_streams
        assert persisted["laps"] == candidate_laps
        process.assert_awaited_once()

    asyncio.run(_run())
