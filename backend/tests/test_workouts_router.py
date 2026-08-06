from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.routers import workouts as workouts_router


def _override(db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db


def _teardown():
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_dt_handles_none_datetime_and_z_suffix():
    from datetime import datetime

    assert workouts_router._parse_dt(None) is None
    dt = datetime(2026, 5, 20, 10, 0)
    assert workouts_router._parse_dt(dt) is dt
    assert workouts_router._parse_dt("2026-05-20T10:00:00Z") is not None
    assert workouts_router._parse_dt("not-a-date") is None
    assert workouts_router._parse_dt(12345) is None


def test_duration_secs_prefers_explicit_field():
    assert workouts_router._duration_secs({"duration_seconds": 1800}) == 1800
    assert workouts_router._duration_secs({"duration_secs": 900}) == 900


def test_duration_secs_falls_back_to_start_end_delta():
    row = {"started_at": "2026-05-20T10:00:00Z", "ended_at": "2026-05-20T11:00:00Z"}
    assert workouts_router._duration_secs(row) == 3600


def test_duration_secs_none_when_no_usable_fields():
    assert workouts_router._duration_secs({}) is None
    assert workouts_router._duration_secs({"duration_seconds": "not-a-number"}) is None


def test_clean_optional_title_strips_and_collapses_blank_to_none():
    assert workouts_router._clean_optional_title(None) is None
    assert workouts_router._clean_optional_title("  ") is None
    assert workouts_router._clean_optional_title("  Ride  ") == "Ride"


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class _ListQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _ListDb:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "workouts"
        return _ListQuery(self._rows)


def test_get_workouts_adds_computed_duration_secs():
    rows = [{"id": "w1", "started_at": "2026-05-20T10:00:00Z", "ended_at": "2026-05-20T11:00:00Z"}]
    _override(_ListDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/workouts")
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()[0]["duration_secs"] == 3600


# ---------------------------------------------------------------------------
# POST / (ingest)
# ---------------------------------------------------------------------------


def test_ingest_workout_queues_background_task():
    _override(_ListDb([]))
    with patch.object(workouts_router, "process_and_save_workout") as mock_process:
        try:
            with TestClient(app) as client:
                res = client.post(
                    "/v1/workouts",
                    json={
                        "source": "manual",
                        "sport": "run",
                        "started_at": "2026-05-20T10:00:00Z",
                        "duration_seconds": 1800,
                    },
                )
        finally:
            _teardown()

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    mock_process.assert_called_once()


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


class _PatchQuery:
    def __init__(self, existing):
        self._existing = existing
        self.updated_payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.updated_payload = payload
        return self

    def execute(self):
        if self.updated_payload is not None:
            merged = {**(self._existing or {}), **self.updated_payload}
            return SimpleNamespace(data=[merged])
        return SimpleNamespace(data=self._existing)


class _PatchDb:
    def __init__(self, existing):
        self.query = _PatchQuery(existing)

    def table(self, name):
        assert name == "workouts"
        return self.query


def test_update_workout_404_when_missing():
    _override(_PatchDb(existing=None))
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/workouts/missing-id", json={"title": "New title"})
    finally:
        _teardown()

    assert res.status_code == 404


def test_update_workout_400_when_no_editable_fields():
    _override(_PatchDb(existing={"id": "w1", "started_at": "2026-05-20T10:00:00Z"}))
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/workouts/w1", json={})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_workout_400_for_blank_sport():
    _override(_PatchDb(existing={"id": "w1", "started_at": "2026-05-20T10:00:00Z"}))
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/workouts/w1", json={"sport": ""})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_workout_400_for_negative_duration():
    _override(_PatchDb(existing={"id": "w1", "started_at": "2026-05-20T10:00:00Z"}))
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/workouts/w1", json={"duration_seconds": -5})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_workout_500_on_unexpected_error():
    _override(_PatchDb(existing={"id": "w1"}))
    with patch.object(workouts_router, "_workout_update_data", side_effect=RuntimeError("boom")):
        try:
            with TestClient(app) as client:
                res = client.patch("/v1/workouts/w1", json={"title": "x"})
        finally:
            _teardown()

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


class _DeleteQuery:
    def __init__(self, exists: bool):
        self._exists = exists
        self.deleted = False

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def delete(self):
        self.deleted = True
        return self

    def execute(self):
        if self.deleted:
            return SimpleNamespace(data=[])
        return SimpleNamespace(data={"id": "w1"} if self._exists else None)


class _DeleteDb:
    def __init__(self, exists: bool):
        self.query = _DeleteQuery(exists)

    def table(self, name):
        assert name == "workouts"
        return self.query


def test_delete_workout_404_when_missing():
    _override(_DeleteDb(exists=False))
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/workouts/missing-id")
    finally:
        _teardown()

    assert res.status_code == 404


def test_delete_workout_success():
    _override(_DeleteDb(exists=True))
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/workouts/w1")
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json() == {"status": "success", "deleted_id": "w1"}


def test_delete_workout_500_on_query_error():
    class _FailingDb:
        def table(self, _name):
            raise RuntimeError("db down")

    _override(_FailingDb())
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/workouts/w1")
    finally:
        _teardown()

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# POST /calculate-tss
# ---------------------------------------------------------------------------


def test_calculate_tss_requires_normalized_power_for_cycling():
    _override(_ListDb([]))
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/workouts/calculate-tss",
                json={
                    "source": "manual",
                    "sport": "cycling",
                    "started_at": "2026-05-20T10:00:00Z",
                    "duration_seconds": 3600,
                    "ftp_at_time": 250,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 400


def test_calculate_tss_computes_for_cycling():
    _override(_ListDb([]))
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/workouts/calculate-tss",
                json={
                    "source": "manual",
                    "sport": "cycling",
                    "started_at": "2026-05-20T10:00:00Z",
                    "duration_seconds": 3600,
                    "norm_power_w": 200,
                    "ftp_at_time": 250,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()["data"]["calculated_tss"] == 64.0


def test_calculate_tss_rejects_non_cycling_sport():
    _override(_ListDb([]))
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/workouts/calculate-tss",
                json={
                    "source": "manual",
                    "sport": "run",
                    "started_at": "2026-05-20T10:00:00Z",
                    "duration_seconds": 1800,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 400
