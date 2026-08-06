from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types

from app.services import ai_coach
from app.services import coach_tools


def _text_part(text, thought=False):
    return SimpleNamespace(text=text, function_call=None, function_response=None, thought=thought)


def _fc_part(name, args=None):
    fc = types.FunctionCall(name=name, args=args or {})
    return SimpleNamespace(text=None, function_call=fc, function_response=None, thought=False)


def _response(parts):
    content = SimpleNamespace(parts=parts)
    cand = SimpleNamespace(content=content, grounding_metadata=None)
    return SimpleNamespace(candidates=[cand], text=None)


def _empty_response():
    return SimpleNamespace(candidates=[], text=None)


CALENDAR = {
    "current_local_date": "2026-05-20",
    "current_local_weekday": "Wednesday",
    "current_local_datetime": "2026-05-20T10:00:00",
    "tomorrow_date": "2026-05-21",
    "tomorrow_weekday": "Thursday",
    "upcoming_weekdays": {"Wednesday": "2026-05-20", "Thursday": "2026-05-21"},
}


@contextlib.contextmanager
def _db_patches():
    """
    Patches shared by every db-path test so only generate_content (and
    whatever else a given test cares about) varies. Explicitly stubs
    retrieve_relevant_memories/should_skip_rag_for_message (rather than
    letting a bare MagicMock db flow into them) since RAG would otherwise
    call the real embedding API (_client.models.embed_content), which is not
    mocked here and would attempt a real network call.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(ai_coach, "_load_conversation_history", return_value=[]))
        stack.enter_context(patch.object(ai_coach, "_athlete_local_calendar", return_value=dict(CALENDAR)))
        stack.enter_context(patch.object(ai_coach.gemini_quota, "wait_for_slot"))
        stack.enter_context(patch.object(ai_coach.time, "sleep"))
        stack.enter_context(patch.object(ai_coach, "should_skip_rag_for_message", return_value=True))
        stack.enter_context(patch.object(ai_coach, "_summarize_training_load", return_value={}))
        stack.enter_context(patch.object(ai_coach, "_summarize_biometrics", return_value={}))
        stack.enter_context(
            patch.object(ai_coach, "_summarize_athlete_profile", return_value={"timezone_offset_min": 0})
        )
        yield


# ---------------------------------------------------------------------------
# No-db path
# ---------------------------------------------------------------------------


def test_agentic_no_db_returns_extracted_message():
    with patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=_response([_text_part("<response>All good!</response>")]),
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        text, sources = ai_coach.get_coach_response_agentic("ath-1", "hi", db=None)
    assert text == "All good!"
    assert sources == []


def test_agentic_called_from_async_context_raises():
    async def _inner():
        ai_coach.get_coach_response_agentic("ath-1", "hi", db=MagicMock())

    import asyncio

    with pytest.raises(RuntimeError, match="async context"):
        asyncio.run(_inner())


# ---------------------------------------------------------------------------
# With db: plain text reply, no tools
# ---------------------------------------------------------------------------


def test_agentic_with_db_plain_text_reply():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=_response([_text_part("<response>Nice work on that ride!</response>")]),
    ):
        text, sources = ai_coach.get_coach_response_agentic(
            "ath-1", "how'd my ride look", db=db, conversation_id=None
        )
    assert text == "Nice work on that ride!"
    assert sources == []


def test_agentic_no_candidates_falls_back():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", return_value=_empty_response()
    ):
        text, sources = ai_coach.get_coach_response_agentic("ath-1", "hi", db=db)
    assert text == "Unable to complete coach response."


def test_agentic_no_content_parts_falls_back():
    db = MagicMock()
    empty_cand_response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))], text=None
    )
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", return_value=empty_cand_response
    ):
        text, sources = ai_coach.get_coach_response_agentic("ath-1", "hi", db=db)
    assert text == "Unable to complete coach response."


# ---------------------------------------------------------------------------
# Tool calling loop
# ---------------------------------------------------------------------------


def test_agentic_single_tool_call_then_final_reply():
    db = MagicMock()
    responses = [
        _response([_fc_part("get_recent_workouts", {"limit": 5})]),
        _response([_text_part("<response>You had 3 rides this week.</response>")]),
    ]
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(
        coach_tools.TOOL_HANDLERS, {"get_recent_workouts": lambda args, athlete_id, db: {"workouts": []}}
    ):
        text, sources = ai_coach.get_coach_response_agentic("ath-1", "how many rides this week", db=db)
    assert text == "You had 3 rides this week."


def test_agentic_unknown_tool_name_reports_error_to_model():
    db = MagicMock()
    responses = [
        _response([_fc_part("nonexistent_tool", {})]),
        _response([_text_part("<response>Handled it anyway.</response>")]),
    ]
    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=responses):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "do the thing", db=db)
    assert text == "Handled it anyway."


def test_agentic_tool_handler_exception_is_reported_as_error_result():
    db = MagicMock()

    def _raising_handler(args, athlete_id, db):
        raise RuntimeError("handler exploded")

    responses = [
        _response([_fc_part("get_recent_workouts", {})]),
        _response([_text_part("<response>Sorted despite the hiccup.</response>")]),
    ]
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(coach_tools.TOOL_HANDLERS, {"get_recent_workouts": _raising_handler}):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "how'd it go", db=db)
    assert text == "Sorted despite the hiccup."


def test_agentic_schedule_workout_tracks_planned_date_for_language_correction():
    db = MagicMock()
    responses = [
        _response([_fc_part("schedule_workout", {"date": "2026-05-21"})]),
        _response([_text_part("<response>Scheduled for today, all set.</response>")]),
    ]

    def _schedule_handler(args, athlete_id, db):
        return {"planned_date": "2026-05-21", "status": "success"}

    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(coach_tools.TOOL_HANDLERS, {"schedule_workout": _schedule_handler}):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "schedule a ride tomorrow", db=db)
    # 2026-05-21 is tomorrow_date in CALENDAR -- "today" should be corrected to "tomorrow".
    assert "tomorrow" in text.lower()


def test_agentic_max_hops_exhausted_returns_fallback():
    db = MagicMock()
    # Every hop returns a tool call, never a final text response -> loop runs out.
    always_tool_call = _response([_fc_part("get_recent_workouts", {})])
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", return_value=always_tool_call
    ), patch.dict(
        coach_tools.TOOL_HANDLERS, {"get_recent_workouts": lambda a, b, c: {"workouts": []}}
    ), patch.object(ai_coach, "_agentic_max_tool_hops", return_value=2):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "hi", db=db)
    assert text == "Unable to complete coach response."


# ---------------------------------------------------------------------------
# Deterministic clear_training_plans backstop
# ---------------------------------------------------------------------------


def test_agentic_clear_this_week_backstop_calls_handler_directly():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=_response([_text_part("<response>Cleared your plan for this week.</response>")]),
    ), patch.object(
        ai_coach.coach_tools, "handle_clear_training_plans", return_value={"status": "success", "deleted": 3}
    ) as mock_clear:
        text, _ = ai_coach.get_coach_response_agentic(
            "ath-1", "please clear my plan this week", db=db
        )
    mock_clear.assert_called_once()
    assert text == "Cleared your plan for this week."


def test_agentic_clear_next_week_backstop():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=_response([_text_part("<response>Cleared next week.</response>")]),
    ), patch.object(
        ai_coach.coach_tools, "handle_clear_training_plans", return_value={"status": "success"}
    ) as mock_clear:
        ai_coach.get_coach_response_agentic("ath-1", "delete my calendar next week", db=db)
    mock_clear.assert_called_once()


def test_agentic_clear_without_week_qualifier_skips_backstop():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=_response([_text_part("<response>Sure, which workout?</response>")]),
    ), patch.object(ai_coach.coach_tools, "handle_clear_training_plans") as mock_clear:
        ai_coach.get_coach_response_agentic("ath-1", "remove my workout", db=db)
    mock_clear.assert_not_called()


# ---------------------------------------------------------------------------
# Hop-error handling
# ---------------------------------------------------------------------------


def test_agentic_hop_error_after_mutating_tool_reports_honest_partial_success():
    db = MagicMock()
    responses = [
        _response([_fc_part("log_workout", {})]),
        RuntimeError("permanent failure, no retry signature"),
    ]
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(coach_tools.TOOL_HANDLERS, {"log_workout": lambda a, b, c: {"status": "success"}}):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "log my workout", db=db)
    assert "made that change" in text


def test_agentic_hop_error_after_readonly_tool_reports_generic_error():
    db = MagicMock()
    responses = [
        _response([_fc_part("get_recent_workouts", {})]),
        RuntimeError("permanent failure"),
    ]
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(
        coach_tools.TOOL_HANDLERS, {"get_recent_workouts": lambda a, b, c: {"workouts": []}}
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "how'd I do", db=db)
    assert "ran into an error" in text


def test_agentic_hop_error_with_no_prior_tool_reraises():
    db = MagicMock()
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=RuntimeError("total failure")
    ):
        with pytest.raises(RuntimeError, match="total failure"):
            ai_coach.get_coach_response_agentic("ath-1", "hi", db=db)


def test_agentic_transient_error_retries_then_succeeds():
    db = MagicMock()
    call_count = {"n": 0}

    def _side_effect(*, model, contents, config):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("503 UNAVAILABLE")
        return _response([_text_part("<response>Recovered after retry.</response>")])

    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=_side_effect):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "hi", db=db)
    assert call_count["n"] == 2
    assert text == "Recovered after retry."


def test_agentic_falls_back_to_second_model_on_overload():
    db = MagicMock()
    seen_models = []

    def _side_effect(*, model, contents, config):
        seen_models.append(model)
        if model == "primary-model":
            raise RuntimeError("quota exceeded for primary")
        return _response([_text_part("<response>Fallback model handled it.</response>")])

    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=_side_effect
    ), patch.object(ai_coach.settings, "GEMINI_FALLBACK_MODEL", "fallback-model"):
        text, _ = ai_coach.get_coach_response_agentic(
            "ath-1", "hi", db=db, model_name="primary-model"
        )
    assert seen_models[0] == "primary-model"
    assert "fallback-model" in seen_models
    assert text == "Fallback model handled it."


# ---------------------------------------------------------------------------
# Progress callback plumbing
# ---------------------------------------------------------------------------


def test_agentic_progress_callback_receives_context_and_thinking_and_tool_events():
    db = MagicMock()
    events = []
    responses = [
        _response([_fc_part("get_recent_workouts", {})]),
        _response([_text_part("<response>Done.</response>")]),
    ]
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", side_effect=responses
    ), patch.dict(
        coach_tools.TOOL_HANDLERS, {"get_recent_workouts": lambda a, b, c: {"workouts": []}}
    ):
        ai_coach.get_coach_response_agentic("ath-1", "hi", db=db, progress_callback=events.append)
    statuses = [e["status"] for e in events]
    assert "context_ready" in statuses
    assert "thinking" in statuses
    assert "tool" in statuses
