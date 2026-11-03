"""Unit tests for AstrapheTokenVerifier — the one place that decides whether a bearer
token is accepted, independent of any HTTP transport. Same style as backend/tests'
direct dependency tests (e.g. test_dependencies_direct.py tests get_current_athlete)."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from astraphe_mcp.auth.token_verifier import AstrapheTokenVerifier


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'ES256'})}.{enc(claims)}.sig"


@pytest.mark.asyncio
async def test_verify_token_valid_returns_access_token():
    verifier = AstrapheTokenVerifier()
    token = _jwt({"sub": "user-123", "client_id": "claude-desktop"})
    fake_user = SimpleNamespace(id="user-123", app_metadata={})
    with patch.object(
        AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=fake_user))
    ):
        result = await verifier.verify_token(token)

    assert result is not None
    assert result.token == token
    assert result.subject == "user-123"
    assert result.client_id == "claude-desktop"
    assert "astraphe:read" in result.scopes


@pytest.mark.asyncio
async def test_verify_token_without_client_id_claim_is_rejected():
    """An ordinary app session token (no client_id claim) must not be accepted by MCP."""
    verifier = AstrapheTokenVerifier()
    fake_user = SimpleNamespace(id="user-123", app_metadata={"client_id": "spoofed-in-metadata"})
    with patch.object(
        AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=fake_user))
    ):
        result = await verifier.verify_token(_jwt({"sub": "user-123", "role": "authenticated"}))

    assert result is None


@pytest.mark.asyncio
async def test_verify_token_no_user_returns_none():
    verifier = AstrapheTokenVerifier()
    with patch.object(AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=None))):
        result = await verifier.verify_token("expired-or-revoked-token")

    assert result is None


@pytest.mark.asyncio
async def test_verify_token_raises_returns_none():
    """An invalid/malformed token should fail closed, not raise out of verify_token."""
    verifier = AstrapheTokenVerifier()
    with patch.object(AstrapheTokenVerifier, "_get_user", new=AsyncMock(side_effect=Exception("bad token"))):
        result = await verifier.verify_token("garbage")

    assert result is None
