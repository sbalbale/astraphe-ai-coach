"""Exercises real tool registration + dispatch (astraphe_mcp.server.build_mcp_server(),
astraphe_mcp.tools._call.call_handler) end to end in-process, via MCPServer.call_tool() —
no HTTP transport needed for this. Business-logic coverage for the underlying handlers
themselves (handle_list_workouts, etc.) already lives in backend/tests/test_coach_tools*.py;
these tests only cover the new MCP-specific glue: auth wiring, athlete resolution, and
that each registered tool actually reaches TOOL_HANDLERS with the right name/args shape.
"""
from __future__ import annotations

import json

import pytest

from astraphe_mcp.server import build_mcp_server
from astraphe_mcp.tools._call import call_handler


@pytest.fixture
def mcp(fake_authenticated_call):
    return build_mcp_server()


def _result_dict(call_tool_result) -> dict:
    text = call_tool_result.content[0].text
    return json.loads(text)


@pytest.mark.asyncio
async def test_all_v1_tools_are_registered(mcp):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "list_workouts",
        "get_workout_summary",
        "get_workout_streams_window",
        "list_planned_workouts",
        "get_training_load_series",
        "get_biometrics_for_dates",
        "summarize_workouts",
        "compare_workouts",
        "get_athlete_zones",
        "list_memories",
        "simulate_training_impact",
        "calculate_nutrition",
    }


@pytest.mark.asyncio
async def test_list_workouts_returns_athlete_scoped_data(mcp, fake_authenticated_call):
    fake_authenticated_call._table_seeds["workouts"] = [
        {"id": "w1", "sport": "run", "title": "Morning Run", "started_at": "2026-08-01T06:00:00Z",
         "duration_seconds": 1800, "distance_m": 5000, "tss": 40.0, "strain_score": 10,
         "avg_hr": 150, "avg_power_w": None, "source": "manual"},
    ]
    result = await mcp.call_tool("list_workouts", {"limit": 5})
    assert result.is_error is not True
    body = _result_dict(result)
    assert body.get("count") == 1 or len(body.get("workouts", [])) == 1


@pytest.mark.asyncio
async def test_get_athlete_zones_no_args_required(mcp):
    result = await mcp.call_tool("get_athlete_zones", {})
    assert result.is_error is not True


@pytest.mark.asyncio
async def test_call_handler_rejects_unknown_tool(fake_authenticated_call):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        await call_handler("not_a_real_tool", {})


@pytest.mark.asyncio
async def test_call_handler_requires_authentication(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr("astraphe_mcp.tools._call.get_access_token", lambda: None)
    with pytest.raises(ToolError, match="Not authenticated"):
        await call_handler("list_workouts", {})


@pytest.mark.asyncio
async def test_none_args_are_dropped_before_reaching_handler(fake_authenticated_call, monkeypatch):
    """MCPServer always passes every declared parameter (None for unset optional ones);
    handlers expect Gemini-style omission of unset keys, not explicit nulls."""
    captured = {}

    def fake_handler(args, athlete_id, db):
        captured.update(args)
        return {"ok": True}

    monkeypatch.setitem(__import__("app.services.coach_tools", fromlist=["TOOL_HANDLERS"]).TOOL_HANDLERS,
                         "list_workouts", fake_handler)

    await call_handler("list_workouts", {"on_date": None, "limit": 5, "sport": None})

    assert captured == {"limit": 5}
