"""
Tests for app.services.token_crypto — the shared encrypt/decrypt helpers every
provider (WHOOP, Strava, intervals.icu, Garmin) routes its oauth_tokens
access_token/refresh_token writes and reads through.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services import token_crypto


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    token_crypto._fernet.cache_clear()
    yield
    token_crypto._fernet.cache_clear()


def test_encrypt_oauth_fields_encrypts_present_secret_fields(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    payload = {
        "athlete_id": "ath-1",
        "provider": "whoop",
        "access_token": "raw-access-abc",
        "refresh_token": "raw-refresh-xyz",
        "expires_at": "2026-01-01T00:00:00Z",
    }
    out = token_crypto.encrypt_oauth_fields(payload)

    assert out["access_token"].startswith("gAAAAA")
    assert out["refresh_token"].startswith("gAAAAA")
    assert "raw-access-abc" not in out["access_token"]
    assert "raw-refresh-xyz" not in out["refresh_token"]
    # Non-secret fields pass through untouched.
    assert out["athlete_id"] == "ath-1"
    assert out["expires_at"] == "2026-01-01T00:00:00Z"
    # Original payload dict is not mutated in place.
    assert payload["access_token"] == "raw-access-abc"


def test_encrypt_oauth_fields_ignores_missing_or_none_fields(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    # Partial updates (e.g. an expires_at-only patch, or an explicit
    # refresh_token=None for API-key providers) must pass through unchanged.
    payload = {"athlete_id": "ath-1", "provider": "intervals_icu", "refresh_token": None}
    out = token_crypto.encrypt_oauth_fields(payload)
    assert out == payload


def test_encrypt_decrypt_oauth_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    row = {
        "athlete_id": "ath-1",
        "provider": "strava",
        "access_token": "strava-access",
        "refresh_token": "strava-refresh",
    }
    stored = token_crypto.encrypt_oauth_fields(row)
    restored = token_crypto.decrypt_oauth_row(stored)

    assert restored["access_token"] == "strava-access"
    assert restored["refresh_token"] == "strava-refresh"


def test_decrypt_oauth_row_accepts_legacy_plaintext(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    # A row written before the key existed (plaintext) must still decrypt cleanly.
    legacy_row = {"access_token": "plain-access", "refresh_token": "plain-refresh"}
    restored = token_crypto.decrypt_oauth_row(legacy_row)
    assert restored == legacy_row


def test_decrypt_oauth_row_fails_closed_on_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()
    stored = token_crypto.encrypt_oauth_fields({"access_token": "abc", "refresh_token": "def"})

    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    restored = token_crypto.decrypt_oauth_row(stored)
    # Fails closed (None), not raise and not ciphertext — callers already treat
    # a missing token as "needs reconnect".
    assert restored["access_token"] is None
    assert restored["refresh_token"] is None


def test_decrypt_oauth_row_none_passthrough():
    assert token_crypto.decrypt_oauth_row(None) is None


def test_no_key_configured_is_plaintext_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", None)
    token_crypto._fernet.cache_clear()

    payload = {"access_token": "abc", "refresh_token": "def"}
    stored = token_crypto.encrypt_oauth_fields(payload)
    assert stored == payload  # unchanged — no key means plaintext (dev-mode fallback)
    assert token_crypto.decrypt_oauth_row(stored) == payload
