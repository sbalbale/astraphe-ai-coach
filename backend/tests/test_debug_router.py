from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db
from app.main import app


class _CountQuery:
    def __init__(self, rows=None, count=0):
        self._rows = rows or []
        self._count = count

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows, count=self._count)


class _DebugDb:
    def __init__(self, athlete_row=None):
        self._athlete_row = athlete_row

    def table(self, name: str):
        if name == "athletes":
            rows = [self._athlete_row] if self._athlete_row else []
            return _CountQuery(rows=rows)
        return _CountQuery(rows=[], count=3)


def test_debug_connection_404s_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: _DebugDb()
    try:
        with TestClient(app) as client:
            res = client.get("/v1/debug/connection")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 404


def test_debug_connection_reports_counts_in_development(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    athlete_row = {
        "id": "athlete-1",
        "user_id": "user-1",
        "display_name": "Test Athlete",
        "created_at": "2026-01-01T00:00:00Z",
    }
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: _DebugDb(athlete_row=athlete_row)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/debug/connection")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert body["backend_env"] == "development"
    assert body["athlete"] == athlete_row
    assert body["counts_visible_under_rls"] == {
        "workouts": 3,
        "biometrics": 3,
        "training_plans": 3,
    }


def test_debug_connection_athlete_null_when_no_row(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: _DebugDb(athlete_row=None)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/debug/connection")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json()["athlete"] is None
