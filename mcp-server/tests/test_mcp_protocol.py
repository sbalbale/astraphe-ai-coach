"""HTTP-level protocol tests against the real ASGI app (astraphe_mcp.asgi's
streamable_http_app()) — the actual wire surface a client like Claude Desktop talks to,
not just the in-process MCPServer API test_read_tools.py exercises. Mirrors the manual
verification already done against a live uvicorn + real local Supabase (see
docs/MCP_SERVER.md); this automates the parts of that check that don't need a real
Supabase OAuth token (discovery metadata, the 401 challenge shape).

Authenticated request/response-body assertions are deliberately left to manual/staging
verification against a real Supabase-issued token (see docs/MCP_SERVER.md's Phase 1
verification checklist) rather than faked here — token verification is exercised
thoroughly in test_token_verifier.py instead.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from astraphe_mcp.server import build_mcp_server


@pytest.fixture
def app():
    return build_mcp_server().streamable_http_app()


def test_protected_resource_metadata_is_published(app):
    client = TestClient(app)
    resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    # Must be a scope GoTrue's OAuth Server actually supports (openid/profile/email/
    # phone) — a custom scope here gets rejected by GoTrue at /oauth/authorize before a
    # client can ever get a token. See server.py's required_scopes comment.
    assert body["scopes_supported"] == ["openid"]
    assert body["bearer_methods_supported"] == ["header"]


@pytest.mark.asyncio
async def test_required_scopes_are_a_subset_of_what_the_verifier_grants(app, monkeypatch):
    """Regression test: server.py's AuthSettings(required_scopes=...) must only list
    scopes AstrapheTokenVerifier actually puts on a verified AccessToken. A published
    required scope the verifier never grants means every real login gets rejected with
    403 insufficient_scope even after a successful GoTrue token exchange — exactly what
    happened when required_scopes was ["astraphe:read"] but the verifier granted a
    different set."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from astraphe_mcp.auth.token_verifier import AstrapheTokenVerifier

    client = TestClient(app)
    published_scopes = client.get("/.well-known/oauth-protected-resource").json()["scopes_supported"]

    verifier = AstrapheTokenVerifier()
    fake_user = SimpleNamespace(id="user-123", app_metadata={})
    with patch.object(
        AstrapheTokenVerifier, "_get_user", new=AsyncMock(return_value=SimpleNamespace(user=fake_user))
    ):
        access_token = await verifier.verify_token("a-valid-token")

    assert access_token is not None
    for scope in published_scopes:
        assert scope in access_token.scopes, (
            f"'{scope}' is published as required/supported but AstrapheTokenVerifier "
            f"never grants it (grants {access_token.scopes}) — every real login would 403"
        )


def test_unauthenticated_request_gets_401_with_challenge(app):
    client = TestClient(app)
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401
    www_auth = resp.headers.get("www-authenticate", "")
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth


def test_garbage_bearer_token_also_gets_401(app, monkeypatch):
    # Stub verify_token rather than letting it hit a real Supabase instance — this test
    # asserts the 401 wiring, not token-verification behavior (that's test_token_verifier.py).
    from astraphe_mcp.auth.token_verifier import AstrapheTokenVerifier

    async def always_reject(self, token):
        return None

    monkeypatch.setattr(AstrapheTokenVerifier, "verify_token", always_reject)

    client = TestClient(app)
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer not-a-real-token",
        },
    )
    assert resp.status_code == 401
