"""Shared plumbing for dispatching an MCP tool call into coach_tools.TOOL_HANDLERS.

Every tool function in read_tools.py builds a plain args dict from its typed parameters
and calls `call_handler(name, args)` — this is the one place that resolves the caller's
identity, builds an RLS-scoped DB client, and invokes the (already-tested, Gemini-agnostic)
handler from backend/app/services/coach_tools.py.
"""
from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError

from astraphe_mcp.db import AthleteProfileNotFound, get_scoped_db, resolve_athlete_id


def _clean(args: dict[str, Any]) -> dict[str, Any]:
    """Drop unset (None) optional args so handlers see the same shape Gemini produces
    (it omits keys entirely for arguments the model didn't set, rather than sending null)."""
    return {k: v for k, v in args.items() if v is not None}


async def call_handler(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    access_token_info = get_access_token()
    if access_token_info is None:
        raise ToolError("Not authenticated")

    from app.dependencies import run_supabase_call  # backend/app on PYTHONPATH, see docs/MCP_SERVER.md
    from app.services.coach_tools import TOOL_HANDLERS  # same import boundary

    db = get_scoped_db(access_token_info.token)
    try:
        athlete_id = await resolve_athlete_id(db, access_token_info.token)
    except AthleteProfileNotFound as e:
        raise ToolError(str(e)) from e

    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ToolError(f"Unknown tool: {tool_name}")

    cleaned = _clean(args)
    try:
        return await run_supabase_call(lambda: handler(cleaned, athlete_id, db))
    except Exception as e:
        # Translate into an MCP tool-error result rather than letting a raw
        # FastAPI HTTPException (from run_supabase_call) or Postgres exception
        # propagate — the MCP client should see a clean error message, not a
        # framework-specific exception type.
        detail = getattr(e, "detail", None) or str(e)
        raise ToolError(f"{tool_name} failed: {detail}") from e
