from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.models.workout import WorkoutPayload, WorkoutUpdatePayload
from app.routers import workouts as workouts_router


def test_workout_list_columns_include_source_ids():
    assert "source_ids" in workouts_router._WORKOUT_LIST_COLUMNS


def test_workout_payload_accepts_average_watts_aliases():
    base = {
        "source": "manual",
        "sport": "bike",
        "started_at": "2026-05-20T10:00:00Z",
        "duration_seconds": 3600,
    }

    assert WorkoutPayload(**base, avg_power_w=245).average_power == 245
    assert WorkoutPayload(**base, average_watts=246).average_power == 246
    assert WorkoutPayload(**base, average_power=247).average_power == 247


def test_workout_update_payload_tracks_average_watts_as_editable_field():
    payload = WorkoutUpdatePayload(avg_power_w=230)

    assert payload.average_power == 230
    assert "average_power" in payload.model_fields_set


class _WorkoutTableQuery:
    def __init__(self, db: "_WorkoutDb"):
        self.db = db
        self._single = False
        self._update_payload: dict | None = None

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
            self.db.last_update = dict(self._update_payload)
            self.db.row.update(self._update_payload)
            return SimpleNamespace(data=[dict(self.db.row)])
        if self._single:
            return SimpleNamespace(data=dict(self.db.row))
        return SimpleNamespace(data=[dict(self.db.row)])


class _WorkoutDb:
    def __init__(self):
        self.row = {
            "id": "workout-1",
            "athlete_id": "athlete-1",
            "source": "strava",
            "strava_activity_id": 123,
            "sport": "bike",
            "title": "Old ride",
            "started_at": "2026-05-20T10:00:00+00:00",
            "ended_at": "2026-05-20T11:00:00+00:00",
            "duration_seconds": 3600,
            "distance_m": 20000,
            "avg_hr": 140,
            "avg_power_w": None,
            "norm_power_w": None,
        }
        self.last_update: dict | None = None

    def table(self, name: str):
        assert name == "workouts"
        return _WorkoutTableQuery(self)


def test_patch_workout_updates_only_editable_scalar_fields(monkeypatch):
    fake_db = _WorkoutDb()
    refresh_calls: list[tuple[str, str]] = []

    def _fake_recalculate_tss_history(athlete_id: str, _db):
        refresh_calls.append(("tss", athlete_id))

    def _fake_refresh_daily_strain(_db, athlete_id: str, day):
        refresh_calls.append(("strain", f"{athlete_id}:{day.isoformat()}"))

    monkeypatch.setattr(workouts_router, "recalculate_tss_history", _fake_recalculate_tss_history)
    monkeypatch.setattr(workouts_router, "_refresh_daily_strain_for_day_sync", _fake_refresh_daily_strain)

    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        with TestClient(app) as client:
            res = client.patch(
                "/v1/workouts/workout-1",
                json={
                    "sport": "bike",
                    "started_at": "2026-05-21T09:30:00Z",
                    "duration_seconds": 3900,
                    "title": "",
                    "distance_m": None,
                    "avg_hr": 150,
                    "max_hr": None,
                    "avg_power_w": 230,
                    "norm_power_w": 250,
                },
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["workout"]["avg_power_w"] == 230

    assert fake_db.last_update is not None
    assert fake_db.last_update["sport"] == "bike"
    assert fake_db.last_update["title"] is None
    assert fake_db.last_update["distance_m"] is None
    assert fake_db.last_update["avg_hr"] == 150
    assert fake_db.last_update["max_hr"] is None
    assert fake_db.last_update["avg_power_w"] == 230
    assert fake_db.last_update["norm_power_w"] == 250
    assert fake_db.last_update["duration_seconds"] == 3900
    assert fake_db.last_update["ended_at"] == "2026-05-21T10:35:00+00:00"
    assert "source" not in fake_db.last_update
    assert "strava_activity_id" not in fake_db.last_update
    assert ("tss", "athlete-1") in refresh_calls
    assert ("strain", "athlete-1:2026-05-20") in refresh_calls
    assert ("strain", "athlete-1:2026-05-21") in refresh_calls
