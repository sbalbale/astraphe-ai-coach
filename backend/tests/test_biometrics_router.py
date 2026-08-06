from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.routers import biometrics as biometrics_router
from app.routers.biometrics import _attach_running_zscores


def test_attach_running_zscores_noop_on_empty_rows():
    rows: list[dict] = []
    _attach_running_zscores(rows, "hrv_rmssd", "hrv_z")
    assert rows == []


def test_attach_running_zscores_first_value_is_zero():
    rows = [{"hrv_rmssd": 50.0}]
    _attach_running_zscores(rows, "hrv_rmssd", "hrv_z")
    assert rows[0]["hrv_z"] == 0.0


def test_attach_running_zscores_none_for_missing_or_zero_values():
    rows = [{"hrv_rmssd": None}, {"hrv_rmssd": 0}]
    _attach_running_zscores(rows, "hrv_rmssd", "hrv_z")
    assert rows[0]["hrv_z"] is None
    assert rows[1]["hrv_z"] is None


def test_attach_running_zscores_computes_deviation_after_baseline():
    rows = [{"hrv_rmssd": v} for v in [50.0, 55.0, 80.0]]
    _attach_running_zscores(rows, "hrv_rmssd", "hrv_z")

    assert rows[0]["hrv_z"] == 0.0
    assert rows[1]["hrv_z"] is None  # not enough history yet (seen < 2)
    assert rows[2]["hrv_z"] is not None
    assert rows[2]["hrv_z"] > 0  # 80 is well above the running baseline


def test_attach_running_zscores_handles_non_numeric_gracefully():
    rows = [{"hrv_rmssd": "not-a-number"}]
    _attach_running_zscores(rows, "hrv_rmssd", "hrv_z")
    assert rows[0]["hrv_z"] is None


class _BiometricsQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _BiometricsDb:
    def __init__(self, bio_rows, period_rows=None):
        self._bio_rows = bio_rows
        self._period_rows = period_rows or []

    def table(self, name):
        if name == "biometrics":
            return _BiometricsQuery(self._bio_rows)
        if name == "sleep_periods":
            return _BiometricsQuery(self._period_rows)
        raise AssertionError(f"unexpected table {name}")


def _override(db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db


def test_get_biometrics_returns_series_with_pagination_defaults():
    rows = [
        {"date": "2026-05-20", "hrv_rmssd": 55, "resting_hr": 48, "sleep_duration_min": 420, "sleep_score": 80},
    ]
    _override(_BiometricsDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/biometrics")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["hrvData"] == [55]
    assert body["sleepData"] == [7.0]
    assert body["sleepScores"] == [80]
    assert body["series"][0]["periods"] == []
    assert body["page"]["limit"] == 60


def test_get_biometrics_respects_explicit_date_range():
    rows = [{"date": "2026-05-20"}]
    _override(_BiometricsDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get(
                "/v1/biometrics",
                params={"start_date": "2026-05-01", "end_date": "2026-05-31"},
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["page"]["start_date"] == "2026-05-01"
    assert body["page"]["end_date"] == "2026-05-31"
    assert body["page"]["has_more"] is False


def test_get_biometrics_all_flag_returns_unbounded_series():
    rows = [{"date": "2026-05-20"}]
    _override(_BiometricsDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/biometrics", params={"all": True})
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["page"]["start_date"] is None
    assert body["page"]["end_date"] is None


def test_get_biometrics_attaches_periods_by_date():
    rows = [{"date": "2026-05-20"}]
    periods = [{"date": "2026-05-20", "started_at": "2026-05-20T22:00:00Z"}]
    _override(_BiometricsDb(rows, period_rows=periods))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/biometrics")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json()["series"][0]["periods"] == periods


def test_ingest_daily_biometrics_queues_background_task():
    _override(_BiometricsDb([]))
    with patch.object(biometrics_router, "process_and_save_biometrics") as mock_process:
        try:
            with TestClient(app) as client:
                res = client.post(
                    "/v1/biometrics/daily",
                    json={
                        "date": "2026-05-20",
                        "source": "manual",
                        "resting_hr": 48,
                        "hrv_rmssd": 55,
                    },
                )
        finally:
            app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["date"] == "2026-05-20"
    mock_process.assert_called_once()
    args = mock_process.call_args[0]
    assert args[0].date.isoformat() == "2026-05-20"
    assert args[1] == "athlete-1"
