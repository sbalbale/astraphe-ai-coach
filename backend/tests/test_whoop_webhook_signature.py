import base64
import hashlib
import hmac
import time

from app.services import whoop


def _whoop_sign(timestamp: str, body: bytes, client_secret: str) -> str:
    msg = timestamp.encode("utf-8") + body
    return base64.b64encode(
        hmac.new(client_secret.encode("utf-8"), msg, hashlib.sha256).digest()
    ).decode("utf-8")


def test_verify_webhook_signature_valid(monkeypatch):
    secret = "aa" * 32
    body = b'{"user_id":1,"type":"sleep.updated"}'
    ts = str(int(time.time() * 1000))
    sig = _whoop_sign(ts, body, secret)

    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(whoop.settings, "WHOOP_CLIENT_SECRET", None)

    assert whoop.verify_webhook_signature(body, sig, ts) is True


def test_verify_webhook_signature_rejects_without_timestamp(monkeypatch):
    secret = "bb" * 32
    body = b"{}"
    sig = _whoop_sign("1716200000000", body, secret)

    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", secret)

    assert whoop.verify_webhook_signature(body, sig, None) is False


def test_verify_webhook_signature_rejects_body_only_hmac(monkeypatch):
    """HMAC over body alone (no timestamp) must not verify."""
    secret = "cc" * 32
    body = b'{"user_id":2}'
    ts = str(int(time.time() * 1000))
    wrong_sig = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", secret)

    assert whoop.verify_webhook_signature(body, wrong_sig, ts) is False


def test_verify_webhook_signature_falls_back_to_client_secret(monkeypatch):
    secret = "dd" * 32
    body = b'{"type":"workout.updated"}'
    ts = str(int(time.time() * 1000))
    sig = _whoop_sign(ts, body, secret)

    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", None)
    monkeypatch.setattr(whoop.settings, "WHOOP_CLIENT_SECRET", secret)

    assert whoop.verify_webhook_signature(body, sig, ts) is True


def test_verify_webhook_signature_rejects_when_no_secret_configured_at_all(monkeypatch):
    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", None)
    monkeypatch.setattr(whoop.settings, "WHOOP_CLIENT_SECRET", None)

    assert whoop.verify_webhook_signature(b"{}", "some-sig", "1716200000000") is False


def test_verify_webhook_signature_rejects_stale_timestamp(monkeypatch):
    """A correctly signed but old event (replay) is rejected."""
    secret = "ee" * 32
    body = b'{"type":"sleep.updated"}'
    ts = str(int((time.time() - 3600) * 1000))
    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", secret)
    assert whoop.verify_webhook_signature(body, _whoop_sign(ts, body, secret), ts) is False


def test_verify_webhook_signature_rejects_non_numeric_timestamp(monkeypatch):
    secret = "ff" * 32
    body = b"{}"
    monkeypatch.setattr(whoop.settings, "WHOOP_WEBHOOK_SECRET", secret)
    assert whoop.verify_webhook_signature(body, _whoop_sign("abc", body, secret), "abc") is False
