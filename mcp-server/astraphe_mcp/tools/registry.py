"""Registers all Astraphe MCP tools onto a server instance."""
from __future__ import annotations

from astraphe_mcp.tools.read_tools import register_read_tools


def register_all(mcp) -> None:
    register_read_tools(mcp)
    # Write tools (log_workout, schedule_workout, save_memory, etc.) land in Phase 3 —
    # see docs/MCP_SERVER.md's phased rollout — behind a distinct write scope.
