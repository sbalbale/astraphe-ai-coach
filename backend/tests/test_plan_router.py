from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_current_user_tier, get_user_db
from app.main import app


class _PlanQuery:
    def __init__(self, rows: list[dict]):
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

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _PlanDb:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def table(self, name: str):
        assert name == "training_plans"
        return _PlanQuery(self._rows)


def _override(tier: str, db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_current_user_tier] = lambda: tier
    app.dependency_overrides[get_user_db] = lambda: db


def test_get_training_plan_rejects_non_premium_tier():
    _override("free", _PlanDb([]))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/plan")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 403


def test_get_training_plan_formats_workouts_and_plan_dict():
    rows = [
        {
            "planned_date": "2026-05-20",
            "sport": "bike",
            "title": "Endurance ride",
            "duration_min": 90,
            "target_tss": 80,
            "status": "planned",
            "description": "Steady zone 2",
        },
        {
            "planned_date": "2026-05-22",
            "sport": "run",
            "title": "Easy run",
            "status": "completed",
        },
    ]
    _override("premium", _PlanDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get(
                "/v1/plan",
                params={"start_date": "2026-05-19", "end_date": "2026-05-25"},
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    body = res.json()
    assert len(body["workouts"]) == 2
    assert body["workouts"][0]["type"] == "bike"
    assert body["workouts"][0]["duration"] == "90m"
    assert body["workouts"][0]["load"] == 80

    assert body["plan"]["20"]["title"] == "Endurance ride"
    assert body["plan"]["20"]["tss"] == 80
    assert body["plan"]["20"]["note"] == "Steady zone 2"
    # Second row omits duration_min/target_tss/description -> defaults apply.
    assert body["plan"]["22"]["duration"] == "0 min"
    assert body["plan"]["22"]["tss"] == 0
    assert body["plan"]["22"]["note"] == ""


def test_get_training_plan_defaults_date_range_when_omitted():
    _override("premium", _PlanDb([]))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/plan")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json() == {"workouts": [], "plan": {}}
