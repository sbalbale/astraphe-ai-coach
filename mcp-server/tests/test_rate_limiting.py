"""astraphe_mcp.tools._call.call_handler's per-athlete rate limit (backend/app/core/
rate_limiter.py's RateLimiter, reused unmodified — see docs/MCP_SERVER.md). Tests use the
in-memory fallback path (no REDIS_URL in the test environment), which is what
mcp-server/tests/conftest.py::reset_mcp_rate_limiter resets between tests.
"""
from __future__ import annotations

import pytest

from astraphe_mcp.config import settings
from astraphe_mcp.tools._call import call_handler


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_configured_limit(fake_authenticated_call, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_RPM", 2)

    await call_handler("get_athlete_zones", {})
    await call_handler("get_athlete_zones", {})

    with pytest.raises(ToolError, match="Rate limit exceeded"):
        await call_handler("get_athlete_zones", {})


@pytest.mark.asyncio
async def test_rate_limit_message_reports_the_configured_rpm(fake_authenticated_call, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_RPM", 1)

    await call_handler("get_athlete_zones", {})
    with pytest.raises(ToolError, match=r"max 1 tool calls per minute"):
        await call_handler("get_athlete_zones", {})


@pytest.mark.asyncio
async def test_rate_limit_is_scoped_per_athlete(fake_authenticated_call, monkeypatch):
    """A different caller (different resolved athlete_id) must not be blocked by another
    athlete's exhausted budget — the rate-limit key includes athlete_id specifically so
    two users of a shared, publicly self-registering (DCR-enabled) server can't starve
    each other. Stubs resolve_athlete_id directly rather than seeding a second `athletes`
    row: the fake Supabase client's .eq() is a no-op (see backend/tests/conftest.py), so
    it can't actually filter a second row out by user_id."""
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_RPM", 1)

    await call_handler("get_athlete_zones", {})  # exhausts MOCK_ATHLETE_ID's budget

    async def fake_resolve_athlete_id(db, access_token, user_id):
        return "a-different-athlete-id"

    monkeypatch.setattr("astraphe_mcp.tools._call.resolve_athlete_id", fake_resolve_athlete_id)

    result = await call_handler("get_athlete_zones", {})
    assert result is not None
