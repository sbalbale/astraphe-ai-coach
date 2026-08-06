from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db
from app.main import app


class _TokenQuery:
    def __init__(self, recorder: dict):
        self._recorder = recorder

    def upsert(self, payload, **kwargs):
        self._recorder["upsert_payload"] = payload
        self._recorder["upsert_kwargs"] = kwargs
        return self

    def delete(self):
        self._recorder["deleted"] = True
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return MagicMock(data=[])


class _TokenDb:
    def __init__(self):
        self.recorder: dict = {}

    def table(self, name: str):
        assert name == "push_tokens"
        return _TokenQuery(self.recorder)


def _override(db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db


def test_register_token_rejects_empty_token():
    _override(_TokenDb())
    try:
        with TestClient(app) as client:
            res = client.post("/v1/notifications/token", json={"token": "", "platform": "ios"})
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 422


def test_register_token_rejects_oversized_token():
    _override(_TokenDb())
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/notifications/token",
                json={"token": "x" * 8193, "platform": "ios"},
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 422


def test_register_token_upserts_and_returns_platform():
    db = _TokenDb()
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/notifications/token",
                json={"token": "device-token-1", "platform": "android"},
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json() == {"status": "registered", "platform": "android"}
    assert db.recorder["upsert_payload"]["athlete_id"] == "athlete-1"
    assert db.recorder["upsert_payload"]["token"] == "device-token-1"
    assert db.recorder["upsert_kwargs"]["on_conflict"] == "athlete_id,token"


def test_unregister_token_deletes_row():
    db = _TokenDb()
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.request(
                "DELETE",
                "/v1/notifications/token",
                json={"token": "device-token-1", "platform": "web"},
            )
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json() == {"status": "removed"}
    assert db.recorder["deleted"] is True


def test_send_test_notification_disabled_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    _override(_TokenDb())
    try:
        with TestClient(app) as client:
            res = client.post("/v1/notifications/test")
    finally:
        app.dependency_overrides = {}

    assert res.status_code == 403


def test_send_test_notification_calls_push_service(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    _override(_TokenDb())

    with patch("app.services.push.send_push_to_athlete", return_value=2) as mock_send:
        try:
            with TestClient(app) as client:
                res = client.post("/v1/notifications/test")
        finally:
            app.dependency_overrides = {}

    assert res.status_code == 200
    assert res.json() == {"status": "sent", "delivered_to": 2}
    mock_send.assert_called_once()
    _, kwargs = mock_send.call_args
    assert kwargs["athlete_id"] == "athlete-1"
    assert kwargs["title"] == "ASTRAPHE"
