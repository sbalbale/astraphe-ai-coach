from __future__ import annotations

from google.genai import types

from app.services import ai_coach


def _model_call(name: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))])


def _tool_response(name: str, response: dict | None = None) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=name, response=response or {})],
    )


def _text(text: str, role: str = "user") -> types.Content:
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


def test_finds_tool_name_from_immediately_preceding_response():
    contents = [_text("hi"), _model_call("get_athlete_zones"), _tool_response("get_athlete_zones")]
    assert ai_coach._tool_names_from_last_function_response(contents) == ["get_athlete_zones"]


def test_skips_past_calendar_reminder_text_appended_after_the_tool_response():
    """Regression for the PR #17 Copilot finding: contents[-1] alone would
    miss this, since the reminder turn has no function_response part."""
    contents = [
        _text("schedule a run tomorrow"),
        _model_call("schedule_workout"),
        _tool_response("schedule_workout", {"planned_date": "2026-08-10"}),
        _text("Reminder: today is 2026-08-09.", role="user"),
    ]
    assert ai_coach._tool_names_from_last_function_response(contents) == ["schedule_workout"]


def test_finds_deterministic_backstop_function_response_with_no_model_call():
    """The clear_training_plans backstop injects a function_response
    directly, with no preceding model-issued function_call at all."""
    contents = [_text("clear my plan this week"), _tool_response("clear_training_plans", {"deleted": 3})]
    assert ai_coach._tool_names_from_last_function_response(contents) == ["clear_training_plans"]


def test_returns_empty_when_no_tool_ever_ran():
    contents = [_text("hi"), _text("hello, how can I help?", role="model")]
    assert ai_coach._tool_names_from_last_function_response(contents) == []


def test_returns_empty_for_empty_contents():
    assert ai_coach._tool_names_from_last_function_response([]) == []


def test_mutating_tool_names_matches_actual_mutating_handlers():
    """Sanity check against coach_tools' real handler set — every name here
    must be a real tool, and the set should only contain handlers that
    actually write data (not e.g. list_workouts)."""
    from app.services import coach_tools

    assert ai_coach._MUTATING_TOOL_NAMES <= set(coach_tools.TOOL_HANDLERS.keys())
    assert "list_workouts" not in ai_coach._MUTATING_TOOL_NAMES
    assert "schedule_workout" in ai_coach._MUTATING_TOOL_NAMES
