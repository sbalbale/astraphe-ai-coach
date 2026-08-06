from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import strava as strava_service


def _run_async(coro):
    return asyncio.run(coro)


class _IngestQuery:
    def __init__(self, db: "_IngestDb", table_name: str):
        self.db = db
        self.table_name = table_name
        self._filters: dict = {}
        self._single = False
        self._update_payload: dict | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def maybe_single(self):
        self._single = True
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            self.db.workout.update(self._update_payload)
            self.db.workout_updates.append(dict(self._update_payload))
            return SimpleNamespace(data=[dict(self.db.workout)])
        if self.table_name == "athletes":
            if not self.db.athlete:
                return SimpleNamespace(data=None)
            if "id" in self._filters and self._filters["id"] != self.db.athlete.get("id"):
                return SimpleNamespace(data=None)
            if "strava_athlete_id" in self._filters and self._filters["strava_athlete_id"] != self.db.athlete.get(
                "strava_athlete_id"
            ):
                return SimpleNamespace(data=None)
            return SimpleNamespace(data=dict(self.db.athlete))
        if self.table_name == "workouts":
            row = dict(self.db.workout) if self.db.workout else None
            return SimpleNamespace(data=row)
        raise AssertionError(f"unexpected table {self.table_name}")


class _IngestDb:
    def __init__(self, athlete=None, workout=None):
        self.athlete = athlete
        self.workout = workout
        self.workout_updates: list[dict] = []

    def table(self, name):
        return _IngestQuery(self, name)


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


def test_ingest_strava_activity_returns_none_when_no_athlete_found():
    db = _IngestDb(athlete=None)
    result = _run_async(
        strava_service.ingest_strava_activity(owner_strava_id=999, activity_id=111, db=db)
    )
    assert result is None


def test_ingest_strava_activity_returns_none_without_valid_token():
    db = _IngestDb(athlete={"id": "athlete-1", "strava_athlete_id": 999})
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value=None)):
        result = _run_async(
            strava_service.ingest_strava_activity(owner_strava_id=999, activity_id=111, db=db)
        )
    assert result is None


def test_ingest_strava_activity_returns_none_when_activity_fetch_empty():
    db = _IngestDb(athlete={"id": "athlete-1", "strava_athlete_id": 999})
    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "get_activity", AsyncMock(return_value={})
    ):
        result = _run_async(
            strava_service.ingest_strava_activity(owner_strava_id=999, activity_id=111, db=db)
        )
    assert result is None


def test_ingest_strava_activity_returns_workout_when_not_linked():
    athlete = {"id": "athlete-1", "strava_athlete_id": 999, "max_hr": 190}
    workout = {"id": "w1", "strava_activity_id": 222, "source_ids": {}}
    db = _IngestDb(athlete=athlete, workout=workout)
    candidate = _activity(111)

    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "get_activity", AsyncMock(return_value=candidate)
    ), patch.object(
        strava_service, "find_or_create_canonical_workout", AsyncMock(return_value=(workout, False))
    ):
        result = _run_async(
            strava_service.ingest_strava_activity(
                owner_strava_id=999, activity_id=111, db=db, athlete_id="athlete-1"
            )
        )

    assert result == workout
    assert db.workout_updates == []


def test_ingest_strava_activity_skips_already_enriched_workout():
    athlete = {"id": "athlete-1", "strava_athlete_id": 999, "max_hr": 190}
    workout = {
        "id": "w1",
        "strava_activity_id": 111,
        "strava_streams_fetched": True,
        "tss": 40,
        "source_ids": {"strava": ["111"]},
    }
    db = _IngestDb(athlete=athlete, workout=workout)
    candidate = _activity(111)

    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "get_activity", AsyncMock(return_value=candidate)
    ), patch.object(
        strava_service, "find_or_create_canonical_workout", AsyncMock(return_value=(workout, False))
    ):
        result = _run_async(
            strava_service.ingest_strava_activity(
                owner_strava_id=999, activity_id=111, db=db, athlete_id="athlete-1"
            )
        )

    assert result == workout
    assert db.workout_updates == []


def test_ingest_strava_activity_full_success_path_updates_and_schedules_hydration():
    athlete = {"id": "athlete-1", "strava_athlete_id": 999, "max_hr": 190, "resting_hr": 50}
    workout = {"id": "w1", "strava_activity_id": None, "source_ids": {}}
    db = _IngestDb(athlete=athlete, workout=workout)
    activity = _activity(111, average_heartrate=145, weighted_average_watts=200)

    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "get_activity", AsyncMock(return_value=activity)
    ), patch.object(
        strava_service,
        "find_or_create_canonical_workout",
        AsyncMock(return_value=({**workout, "strava_activity_id": 111, "source_ids": {"strava": ["111"]}}, True)),
    ), patch.object(
        strava_service, "_load_stored_streams_dict", return_value={}
    ), patch.object(
        strava_service, "get_activity_streams", AsyncMock(return_value={})
    ), patch.object(
        strava_service, "_load_cached_laps_for_workout", return_value=None
    ), patch.object(
        strava_service, "get_activity_laps", AsyncMock(return_value=[])
    ), patch.object(
        strava_service, "_upsert_activity_streams"
    ), patch.object(
        strava_service, "_persist_activity_laps"
    ), patch.object(
        strava_service, "process_and_save_workout", AsyncMock()
    ) as mock_save, patch.object(
        strava_service, "schedule_hydrate_streams_background"
    ) as mock_schedule:
        result = _run_async(
            strava_service.ingest_strava_activity(
                owner_strava_id=999, activity_id=111, db=db, athlete_id="athlete-1"
            )
        )

    assert db.workout_updates  # workout row was updated with strava fields
    assert db.workout_updates[0]["strava_activity_id"] == 111
    mock_save.assert_awaited_once()
    mock_schedule.assert_called_once()  # no streams -> schedule background hydration
    assert result["title"] == activity["name"]


def test_ingest_strava_activity_rowing_extracts_intervals():
    athlete = {"id": "athlete-1", "strava_athlete_id": 999, "max_hr": 190, "resting_hr": 50}
    workout = {"id": "w1", "strava_activity_id": None, "source_ids": {}}
    db = _IngestDb(athlete=athlete, workout=workout)
    activity = _activity(111, sport_type="Rowing", type="Rowing")
    streams = {
        "heartrate": {"data": [140] * 100},
        "distance": {"data": list(range(0, 5000, 50))},
        "time": {"data": list(range(100))},
    }

    with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
        strava_service, "get_activity", AsyncMock(return_value=activity)
    ), patch.object(
        strava_service,
        "find_or_create_canonical_workout",
        AsyncMock(return_value=({**workout, "strava_activity_id": 111, "source_ids": {"strava": ["111"]}}, True)),
    ), patch.object(
        strava_service, "_load_stored_streams_dict", return_value={}
    ), patch.object(
        strava_service, "get_activity_streams", AsyncMock(return_value=streams)
    ), patch.object(
        strava_service, "_load_cached_laps_for_workout", return_value=None
    ), patch.object(
        strava_service, "get_activity_laps", AsyncMock(return_value=[])
    ), patch.object(
        strava_service, "_upsert_activity_streams"
    ), patch.object(
        strava_service, "_persist_activity_laps"
    ), patch.object(
        strava_service, "process_and_save_workout", AsyncMock()
    ), patch.object(
        strava_service, "schedule_hydrate_streams_background"
    ) as mock_schedule:
        result = _run_async(
            strava_service.ingest_strava_activity(
                owner_strava_id=999, activity_id=111, db=db, athlete_id="athlete-1"
            )
        )

    assert "intervals" in db.workout_updates[0]
    mock_schedule.assert_not_called()  # streams were present, no hydration needed
