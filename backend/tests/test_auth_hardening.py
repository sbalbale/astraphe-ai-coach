from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import settings
from app.main import client_ip


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'HS256'})}.{enc(claims)}.sig"


def test_third_party_oauth_tokens_are_rejected():
    with pytest.raises(HTTPException) as exc:
        dependencies.reject_third_party_oauth_token(_jwt({"sub": "u1", "client_id": "mcp-client"}))
    assert exc.value.status_code == 403


def test_first_party_session_tokens_pass():
    dependencies.reject_third_party_oauth_token(_jwt({"sub": "u1", "role": "authenticated"}))
    dependencies.reject_third_party_oauth_token("not-a-jwt")  # unparseable: left to GoTrue


def test_client_ip_uses_rightmost_forwarded_hop():
    req = SimpleNamespace(headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_ip(req) == "203.0.113.9"  # the first entry is client-forgeable
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_ip(req) == "10.0.0.1"


def test_dev_auth_fallback_only_for_local_supabase(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "TEST_ATHLETE_ID", "ath-test")
    monkeypatch.setattr(settings, "SUPABASE_URL", "http://127.0.0.1:55321")
    assert dependencies._dev_auth_fallback_allowed() is True
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://db.astrapheai.com")
    assert dependencies._dev_auth_fallback_allowed() is False
    monkeypatch.setattr(settings, "SUPABASE_URL", "http://127.0.0.1:55321")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert dependencies._dev_auth_fallback_allowed() is False


def test_client_ip_prefers_cloudflare_connecting_ip():
    """Behind Cloudflare + ingress the right-most XFF hop is a proxy (review F5)."""
    req = SimpleNamespace(
        headers={"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "6.6.6.6, 172.70.1.2, 10.42.0.9"},
        client=SimpleNamespace(host="10.42.0.9"),
    )
    assert client_ip(req) == "198.51.100.7"


def test_client_ip_ignores_a_malformed_cloudflare_header():
    req = SimpleNamespace(
        headers={"CF-Connecting-IP": "not-an-ip", "X-Forwarded-For": "203.0.113.9"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.9"
