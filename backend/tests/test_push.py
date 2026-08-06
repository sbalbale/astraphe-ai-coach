from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.services.push as push_module
from app.config import settings


def test_init_firebase_false_without_service_account(monkeypatch):
    push_module._firebase_ready = False
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", None)

    assert push_module._init_firebase() is False


def test_init_firebase_returns_true_when_already_ready():
    push_module._firebase_ready = True
    try:
        assert push_module._init_firebase() is True
    finally:
        push_module._firebase_ready = False


def test_init_firebase_reuses_existing_app(monkeypatch):
    push_module._firebase_ready = False
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", json.dumps({"type": "service_account"}))

    with patch("firebase_admin._apps", {"[DEFAULT]": object()}):
        try:
            assert push_module._init_firebase() is True
        finally:
            push_module._firebase_ready = False


def test_init_firebase_creates_app_when_credentials_valid(monkeypatch):
    push_module._firebase_ready = False
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", json.dumps({"type": "service_account"}))

    with patch("firebase_admin._apps", {}), patch(
        "firebase_admin.credentials.Certificate", return_value=MagicMock()
    ) as mock_cert, patch("firebase_admin.initialize_app") as mock_init:
        try:
            assert push_module._init_firebase() is True
        finally:
            push_module._firebase_ready = False

    mock_cert.assert_called_once()
    mock_init.assert_called_once()


def test_init_firebase_handles_init_failure(monkeypatch):
    push_module._firebase_ready = False
    monkeypatch.setattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "not-valid-json")

    assert push_module._init_firebase() is False
    push_module._firebase_ready = False


def test_send_fcm_false_when_firebase_not_ready():
    with patch.object(push_module, "_init_firebase", return_value=False):
        assert push_module._send_fcm("token", "title", "body", {}) is False


def test_send_fcm_true_on_success():
    with patch.object(push_module, "_init_firebase", return_value=True), patch(
        "firebase_admin.messaging.send", return_value="message-id"
    ) as mock_send:
        assert push_module._send_fcm("token123456", "title", "body", {"a": 1}) is True

    mock_send.assert_called_once()


def test_send_fcm_false_on_send_exception():
    with patch.object(push_module, "_init_firebase", return_value=True), patch(
        "firebase_admin.messaging.send", side_effect=RuntimeError("fcm down")
    ):
        assert push_module._send_fcm("token123456", "title", "body", {}) is False


def test_send_web_push_false_without_vapid_keys(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", None)
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", None)

    assert push_module._send_web_push("{}", "title", "body", {}) is False


def test_send_web_push_true_on_success(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub")

    subscription = json.dumps({"endpoint": "https://push.example/sub"})

    with patch("pywebpush.webpush") as mock_webpush:
        assert push_module._send_web_push(subscription, "title", "body", {}) is True

    mock_webpush.assert_called_once()


def test_send_web_push_false_on_exception(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub")

    # Malformed subscription JSON triggers a json.loads failure inside the try/except.
    assert push_module._send_web_push("not-json", "title", "body", {}) is False


class _PushQuery:
    def __init__(self, profile_row=None, tokens=None):
        self._profile_row = profile_row
        self._tokens = tokens or []
        self._table = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._table == "athletes":
            return SimpleNamespace(data=self._profile_row)
        return SimpleNamespace(data=self._tokens)


class _PushDb:
    def __init__(self, profile_row=None, tokens=None):
        self._q = _PushQuery(profile_row=profile_row, tokens=tokens)

    def table(self, name):
        self._q._table = name
        return self._q


def test_send_push_to_athlete_returns_zero_when_no_tokens():
    db = _PushDb(tokens=[])

    assert push_module.send_push_to_athlete("athlete-1", "T", "B", db) == 0


def test_send_push_to_athlete_respects_disabled_notification_type():
    db = _PushDb(profile_row={"notification_settings": {"coach": False}}, tokens=[{"token": "t1", "platform": "ios"}])

    result = push_module.send_push_to_athlete(
        "athlete-1", "T", "B", db, notification_type="coach"
    )

    assert result == 0


def test_send_push_to_athlete_sends_via_fcm_and_web(monkeypatch):
    tokens = [
        {"token": "ios-token", "platform": "ios"},
        {"token": "web-token", "platform": "web"},
        {"token": "unknown-token", "platform": "carrier-pigeon"},
    ]
    db = _PushDb(tokens=tokens)

    with patch.object(push_module, "_send_fcm", return_value=True) as mock_fcm, patch.object(
        push_module, "_send_web_push", return_value=True
    ) as mock_web:
        result = push_module.send_push_to_athlete("athlete-1", "T", "**B**", db)

    assert result == 2
    mock_fcm.assert_called_once()
    mock_web.assert_called_once()


def test_send_push_to_athlete_returns_zero_on_unexpected_error():
    class _BrokenDb:
        def table(self, _name):
            raise RuntimeError("db down")

    assert push_module.send_push_to_athlete("athlete-1", "T", "B", _BrokenDb()) == 0
