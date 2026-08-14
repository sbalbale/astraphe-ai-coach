"""Unit tests for AstrapheTokenVerifier — the one place that decides whether a bearer
token is accepted, independent of any HTTP transport. Same style as backend/tests'
direct dependency tests (e.g. test_dependencies_direct.py tests get_current_athlete)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from astraphe_mcp.auth.token_verifier import AstrapheTokenVerifier


@pytest.mark.asyncio
async def test_verify_token_valid_returns_access_token():
    verifier = AstrapheTokenVerifier()
    fake_user = SimpleNamespace(id="user-123", app_metadata={"client_id": "claude-desktop"})
    with patch.object(
        AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=fake_user))
    ):
        result = await verifier.verify_token("a-valid-token")

    assert result is not None
    assert result.token == "a-valid-token"
    assert result.subject == "user-123"
    assert result.client_id == "claude-desktop"
    assert "astraphe:read" in result.scopes


@pytest.mark.asyncio
async def test_verify_token_missing_client_id_defaults_empty():
    verifier = AstrapheTokenVerifier()
    fake_user = SimpleNamespace(id="user-123", app_metadata={})
    with patch.object(
        AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=fake_user))
    ):
        result = await verifier.verify_token("a-valid-token")

    assert result is not None
    assert result.client_id == ""


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
