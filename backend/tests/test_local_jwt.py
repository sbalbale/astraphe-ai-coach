"""Local verification of Supabase user JWTs (dependencies.verify_jwt_locally)."""
from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import dependencies as deps

KEY = ec.generate_private_key(ec.SECP256R1())
OTHER = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    # The published public key; a token signed by any other key must fail.
    monkeypatch.setattr(
        deps, "_jwks", lambda: SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=KEY.public_key()))
    )


def _token(key=KEY, alg="ES256", **over):
    claims = {"sub": "user-1", "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 600, **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "k1"})


def test_valid_user_token_verifies():
    assert deps.verify_jwt_locally(_token())["sub"] == "user-1"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(exp=int(time.time()) - 5), id="expired"),
        pytest.param(lambda: _token(aud="other"), id="wrong-audience"),
        pytest.param(lambda: _token(role="service_role"), id="service-role"),
        pytest.param(lambda: _token(role="anon"), id="anon"),
        pytest.param(lambda: _token(sub=None), id="no-sub"),
        pytest.param(lambda: _token(exp=None), id="no-exp"),
        pytest.param(lambda: _token(key=OTHER), id="signed-by-another-key"),
        pytest.param(lambda: _token()[:-4] + "AAAA", id="tampered-signature"),
        pytest.param(lambda: jwt.encode({"sub": "u", "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 600}, "s" * 32, algorithm="HS256"), id="hs256"),
        pytest.param(lambda: jwt.encode({"sub": "u", "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 600}, None, algorithm="none"), id="alg-none"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
def test_untrusted_tokens_are_not_verified_locally(token):
    assert deps.verify_jwt_locally(token()) is None


def test_jwks_failure_falls_back(monkeypatch):
    def boom():
        raise RuntimeError("jwks unreachable")

    monkeypatch.setattr(deps, "_jwks", lambda: SimpleNamespace(get_signing_key_from_jwt=lambda t: boom()))
    assert deps.verify_jwt_locally(_token()) is None  # caller then asks GoTrue


def test_current_athlete_uses_local_claims_without_calling_gotrue(monkeypatch):
    import asyncio

    called = {"gotrue": 0}

    async def fake_get_user(db, token):
        called["gotrue"] += 1
        raise AssertionError("should not be called for a locally verified token")

    async def fake_athlete(db, user_id):
        return f"athlete-of-{user_id}"

    monkeypatch.setattr(deps, "_auth_get_user", fake_get_user)
    monkeypatch.setattr(deps, "_fetch_athlete_id_for_user", fake_athlete)
    creds = SimpleNamespace(credentials=_token())
    assert asyncio.run(deps.get_current_athlete(credentials=creds, db=object())) == "athlete-of-user-1"
    assert called["gotrue"] == 0


def test_third_party_oauth_tokens_still_rejected():
    import asyncio

    from fastapi import HTTPException

    creds = SimpleNamespace(credentials=_token(client_id="mcp-client"))
    with pytest.raises(HTTPException) as e:
        asyncio.run(deps.get_current_athlete(credentials=creds, db=object()))
    assert e.value.status_code == 403
