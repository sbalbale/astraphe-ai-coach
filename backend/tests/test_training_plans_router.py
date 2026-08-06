from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.routers.training_plans import _to_workout_row


def test_to_workout_row_maps_done_and_modified_statuses_to_completed():
    row = {"id": "1", "planned_date": "2026-05-20", "status": "done"}
    assert _to_workout_row(row)["completed"] is True

    row2 = {"id": "2", "planned_date": "2026-05-20", "status": "modified"}
    assert _to_workout_row(row2)["completed"] is True

    row3 = {"id": "3", "planned_date": "2026-05-20", "status": "planned"}
    assert _to_workout_row(row3)["completed"] is False


def test_to_workout_row_applies_defaults_for_missing_fields():
    row = {"id": "1", "planned_date": None}
    mapped = _to_workout_row(row)
    assert mapped["date"] == ""
    assert mapped["title"] == ""
    assert mapped["primary_zone"] == "Endurance"
    assert mapped["duration_minutes"] == 0
    assert mapped["structure"] == []


class _PlanQuery:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []
        self.fail = False
        self.deleted = None

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

    def insert(self, payload):
        self._rows = [{**payload, "id": "new-1"}]
        return self

    def update(self, payload):
        if self._rows:
            self._rows = [{**self._rows[0], **payload}]
        return self

    def delete(self):
        self.deleted = list(self._rows)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("db exploded")
        return SimpleNamespace(data=self._rows)


class _PlanDb:
    def __init__(self, rows=None):
        self.query = _PlanQuery(rows)

    def table(self, name):
        assert name == "training_plans"
        return self.query


def _override(db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db


def _teardown():
    app.dependency_overrides = {}


def test_get_training_plans_maps_rows():
    rows = [{"id": "1", "planned_date": "2026-05-20", "sport": "cycling", "status": "planned"}]
    _override(_PlanDb(rows))
    try:
        with TestClient(app) as client:
            res = client.get("/v1/training-plans")
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body[0]["sport"] == "bike"


def test_get_training_plans_returns_500_on_query_failure():
    db = _PlanDb([])
    db.query.fail = True
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/training-plans")
    finally:
        _teardown()

    assert res.status_code == 500


def test_create_training_plan_inserts_and_returns_mapped_row():
    _override(_PlanDb())
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/training-plans",
                json={
                    "date": "2026-05-20",
                    "title": "Threshold intervals",
                    "sport": "run",
                    "primary_zone": "Threshold",
                    "duration_minutes": 60,
                    "projected_tss": 80,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()["id"] == "new-1"


def test_create_training_plan_returns_500_on_failure():
    db = _PlanDb()
    db.query.fail = True
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/training-plans",
                json={
                    "date": "2026-05-20",
                    "title": "X",
                    "sport": "run",
                    "primary_zone": "Endurance",
                    "duration_minutes": 30,
                    "projected_tss": 20,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 500


def test_update_training_plan_returns_404_when_missing():
    _override(_PlanDb(rows=[]))
    try:
        with TestClient(app) as client:
            res = client.put(
                "/v1/training-plans/missing-id",
                json={
                    "date": "2026-05-20",
                    "title": "X",
                    "sport": "run",
                    "primary_zone": "Endurance",
                    "duration_minutes": 30,
                    "projected_tss": 20,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 404


def test_update_training_plan_returns_mapped_row_on_success():
    db = _PlanDb(rows=[{"id": "plan-1", "planned_date": "2026-05-20"}])
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.put(
                "/v1/training-plans/plan-1",
                json={
                    "date": "2026-05-21",
                    "title": "Updated",
                    "sport": "swim",
                    "primary_zone": "Endurance",
                    "duration_minutes": 45,
                    "projected_tss": 30,
                    "completed": True,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "plan-1"
    assert body["completed"] is True


def test_delete_training_plan_returns_404_when_nothing_deleted():
    _override(_PlanDb(rows=[]))
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/training-plans/missing-id")
    finally:
        _teardown()

    assert res.status_code == 404


def test_delete_training_plan_success():
    _override(_PlanDb(rows=[{"id": "plan-1"}]))
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/training-plans/plan-1")
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json() == {"status": "success", "id": "plan-1"}


def test_delete_training_plans_requires_date_range():
    _override(_PlanDb(rows=[]))
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/training-plans")
    finally:
        _teardown()

    assert res.status_code == 400


def test_delete_training_plans_returns_deleted_count():
    _override(_PlanDb(rows=[{"id": "1"}, {"id": "2"}]))
    try:
        with TestClient(app) as client:
            res = client.delete(
                "/v1/training-plans",
                params={"start_date": "2026-05-01", "end_date": "2026-05-31"},
            )
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json() == {"status": "success", "deleted": 2}


def test_delete_training_plans_returns_500_on_failure():
    db = _PlanDb(rows=[])
    db.query.fail = True
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/training-plans", params={"start_date": "2026-05-01"})
    finally:
        _teardown()

    assert res.status_code == 500
