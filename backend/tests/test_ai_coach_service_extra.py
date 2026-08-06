from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import ai_coach


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------


def _bio_row(**overrides):
    base = {
        "date": "2026-05-20",
        "hrv_rmssd": 55.0,
        "resting_hr": 48,
        "sleep_duration_min": 480,
        "sleep_debt_min": None,
        "skin_temp": 33.0,
    }
    base.update(overrides)
    return base


def _db_for_anomalies(window_rows, profile=None, bio_summary=None, tsb=None):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=list(reversed(window_rows))  # detect_anomalies reverses again to get chronological
    )
    return db


def test_detect_anomalies_no_signals_returns_none():
    window = [_bio_row(date=f"2026-05-{i:02d}") for i in range(1, 10)]
    db = _db_for_anomalies(window)
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        assert ai_coach.detect_anomalies(db, "ath-1") is None


def test_detect_anomalies_query_exception_handled_gracefully():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        assert ai_coach.detect_anomalies(db, "ath-1") is None


def test_detect_anomalies_hrv_z_signal():
    # compute_z_score() reports z=0 when the baseline's EWMA std is degenerate
    # (<=1e-9), so a perfectly constant baseline can never trigger -- give it
    # some realistic spread around 55, then a sharp drop on the latest reading.
    baseline_values = [50, 58, 52, 60, 48, 56, 53, 59, 51, 57, 54, 60, 49, 55]
    window = [
        _bio_row(date=f"2026-05-{i:02d}", hrv_rmssd=v)
        for i, v in enumerate(baseline_values, start=1)
    ]
    window.append(_bio_row(date="2026-05-15", hrv_rmssd=15.0))
    db = _db_for_anomalies(window)
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    assert any(s["metric"] == "hrv_z" for s in result["signals"])


def test_detect_anomalies_sleep_debt_signal_from_explicit_field():
    window = [_bio_row(date="2026-05-20", sleep_debt_min=120)]
    db = _db_for_anomalies(window)
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    assert any(s["metric"] == "sleep_debt_min" and s["value"] == 120 for s in result["signals"])


def test_detect_anomalies_sleep_debt_signal_derived_from_duration():
    window = [_bio_row(date="2026-05-20", sleep_debt_min=None, sleep_duration_min=300)]
    db = _db_for_anomalies(window)
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    signal = next(s for s in result["signals"] if s["metric"] == "sleep_debt_min")
    assert signal["value"] == 180.0  # 480 - 300


def test_detect_anomalies_resting_hr_delta_signal():
    window = [_bio_row(date="2026-05-20")]
    db = _db_for_anomalies(window)
    bio_summary = {
        "available": True,
        "latest": {"resting_hr": 60, "skin_temp": 33.0},
        "avg_7d": {"resting_hr": 50, "skin_temp": 33.0},
    }
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value=bio_summary
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    assert any(s["metric"] == "resting_hr_delta" for s in result["signals"])


def test_detect_anomalies_skin_temp_deviation_signal():
    window = [_bio_row(date=f"2026-05-{i:02d}", skin_temp=33.0) for i in range(14, 20)]
    window.append(_bio_row(date="2026-05-20", skin_temp=34.0))  # +1.0C above 7d avg
    db = _db_for_anomalies(window)
    bio_summary = {
        "available": True,
        "latest": {"resting_hr": 48, "skin_temp": 93.2},
        "avg_7d": {"resting_hr": 48, "skin_temp": 91.4},
    }
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "imperial"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value=bio_summary
    ), patch.object(ai_coach, "_summarize_training_load", return_value={"latest_pmc": None}):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    signal = next(s for s in result["signals"] if s["metric"] == "skin_temp_deviation")
    assert "°F" in signal["latest_value"]


def test_detect_anomalies_tsb_signal():
    window = [_bio_row(date="2026-05-20")]
    db = _db_for_anomalies(window)
    with patch.object(ai_coach, "_summarize_athlete_profile", return_value={"measurement_units": "metric"}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={"available": False}
    ), patch.object(
        ai_coach, "_summarize_training_load", return_value={"latest_pmc": {"tsb": -35.0}}
    ):
        result = ai_coach.detect_anomalies(db, "ath-1")
    assert result is not None
    assert any(s["metric"] == "tsb" and s["value"] == -35.0 for s in result["signals"])


# ---------------------------------------------------------------------------
# _coach_progress / _tool_names_from_last_function_response
# ---------------------------------------------------------------------------


def test_coach_progress_none_callback_is_noop():
    ai_coach._coach_progress(None, "thinking")  # should not raise


def test_coach_progress_calls_callback():
    events = []
    ai_coach._coach_progress(events.append, "thinking", detail="x")
    assert events == [{"status": "thinking", "detail": "x"}]


def test_coach_progress_swallows_callback_exception():
    def _bad_callback(_event):
        raise RuntimeError("boom")

    ai_coach._coach_progress(_bad_callback, "thinking")  # should not raise


def test_tool_names_from_last_function_response_empty_contents():
    assert ai_coach._tool_names_from_last_function_response([]) == []


def test_tool_names_from_last_function_response_finds_most_recent():
    fr1 = SimpleNamespace(name="get_workouts")
    fr2 = SimpleNamespace(name="schedule_workout")
    part_with_fr = SimpleNamespace(function_response=fr2)
    part_without_fr = SimpleNamespace(function_response=None)
    older_content = SimpleNamespace(parts=[SimpleNamespace(function_response=fr1)])
    newer_content = SimpleNamespace(parts=[part_without_fr, part_with_fr])
    plain_text_content = SimpleNamespace(parts=[SimpleNamespace(function_response=None)])
    result = ai_coach._tool_names_from_last_function_response(
        [older_content, newer_content, plain_text_content]
    )
    assert result == ["schedule_workout"]


def test_tool_names_from_last_function_response_no_matches_returns_empty():
    content = SimpleNamespace(parts=[SimpleNamespace(function_response=None)])
    assert ai_coach._tool_names_from_last_function_response([content]) == []


# ---------------------------------------------------------------------------
# build_initialization_message
# ---------------------------------------------------------------------------


def test_build_initialization_message_no_anomalies_returns_greeting():
    db = MagicMock()
    with patch.object(ai_coach, "detect_anomalies", return_value=None), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=SimpleNamespace(text="<response>Ready to train today?</response>"),
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        text, is_proactive = ai_coach.build_initialization_message("ath-1", db)
    assert is_proactive is False
    assert "Ready to train today?" in text


def test_build_initialization_message_with_anomalies_is_proactive():
    db = MagicMock()
    anomalies = {"triggered": True, "signals": [{"metric": "tsb", "value": -35}]}
    with patch.object(ai_coach, "detect_anomalies", return_value=anomalies), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models,
        "generate_content",
        return_value=SimpleNamespace(text="<response>Your TSB is low, take it easy.</response>"),
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        text, is_proactive = ai_coach.build_initialization_message("ath-1", db)
    assert is_proactive is True
    assert "TSB" in text


def test_build_initialization_message_falls_back_when_generation_fails():
    db = MagicMock()
    with patch.object(ai_coach, "detect_anomalies", return_value=None), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models, "generate_content", side_effect=RuntimeError("500 INTERNAL")
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"), patch.object(ai_coach.time, "sleep"):
        text, is_proactive = ai_coach.build_initialization_message("ath-1", db)
    assert is_proactive is False
    assert "focus on today" in text


def test_build_initialization_message_falls_back_with_anomalies_when_generation_fails():
    db = MagicMock()
    anomalies = {"triggered": True, "signals": []}
    with patch.object(ai_coach, "detect_anomalies", return_value=anomalies), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models, "generate_content", side_effect=RuntimeError("permanent failure")
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        text, is_proactive = ai_coach.build_initialization_message("ath-1", db)
    assert is_proactive is True
    assert "recovery-focused plan" in text


def test_build_initialization_message_retries_transient_error_then_succeeds():
    db = MagicMock()
    call_count = {"n": 0}

    def _side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(text="<response>All good, ready when you are.</response>")

    with patch.object(ai_coach, "detect_anomalies", return_value=None), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models, "generate_content", side_effect=_side_effect
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"), patch.object(ai_coach.time, "sleep"):
        text, is_proactive = ai_coach.build_initialization_message("ath-1", db)
    assert call_count["n"] == 2
    assert "ready when you are" in text


def test_build_initialization_message_falls_back_to_second_model_candidate():
    db = MagicMock()
    call_models = []

    def _side_effect(*, model, **kwargs):
        call_models.append(model)
        if model == "primary-model":
            raise RuntimeError("gemini quota exceeded")
        return SimpleNamespace(text="<response>Second model handled it.</response>")

    with patch.object(ai_coach, "detect_anomalies", return_value=None), patch.object(
        ai_coach, "_build_system_context", return_value="ctx"
    ), patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": 0}, {})
    ), patch.object(
        ai_coach._client.models, "generate_content", side_effect=_side_effect
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"), patch.object(
        ai_coach.settings, "GEMINI_FALLBACK_MODEL", "fallback-model"
    ):
        text, _ = ai_coach.build_initialization_message("ath-1", db, model_name="primary-model")
    assert call_models[0] == "primary-model"
    assert "fallback-model" in call_models
    assert "Second model handled it" in text


# ---------------------------------------------------------------------------
# get_coach_response_agentic_async / get_coach_response (thin wrappers)
# ---------------------------------------------------------------------------


def test_get_coach_response_agentic_async_delegates_to_sync_impl():
    with patch.object(
        ai_coach, "get_coach_response_agentic", return_value=("reply", [])
    ) as mock_sync:
        result = _run_async(
            ai_coach.get_coach_response_agentic_async("ath-1", "hi", db=MagicMock())
        )
    assert result == ("reply", [])
    mock_sync.assert_called_once()


def test_get_coach_response_delegates_to_agentic():
    with patch.object(
        ai_coach, "get_coach_response_agentic", return_value=("reply", [{"url": "x"}])
    ) as mock_agentic:
        result = ai_coach.get_coach_response("ath-1", "hi", db=MagicMock())
    assert result == ("reply", [{"url": "x"}])
    mock_agentic.assert_called_once()


# ---------------------------------------------------------------------------
# _assemble_agentic_context_async
# ---------------------------------------------------------------------------


def test_assemble_agentic_context_async_minimal_no_conversation_no_memories():
    db = MagicMock()
    with patch.object(ai_coach, "should_skip_rag_for_message", return_value=True), patch.object(
        ai_coach, "_summarize_training_load", return_value={}
    ), patch.object(ai_coach, "_summarize_biometrics", return_value={}), patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={"timezone_offset_min": 0}
    ):
        result = _run_async(
            ai_coach._assemble_agentic_context_async(db, "ath-1", "thanks", conversation_id=None)
        )
    assert "SYSTEM CONTEXT" in result
    assert '"memories"' not in result
    assert '"conversation"' not in result


def test_assemble_agentic_context_async_includes_memories_and_conversation():
    db = MagicMock()
    with patch.object(ai_coach, "should_skip_rag_for_message", return_value=False), patch.object(
        ai_coach, "retrieve_relevant_memories", return_value=[{"content": "likes trail running", "created_at": "t"}]
    ), patch.object(ai_coach, "_summarize_training_load", return_value={}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={}
    ), patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={"timezone_offset_min": 0}
    ), patch.object(
        ai_coach, "_load_conversation_history", return_value=[{"role": "user", "content": "hi"}]
    ):
        result = _run_async(
            ai_coach._assemble_agentic_context_async(
                db, "ath-1", "what's my plan this week?", conversation_id="conv-1"
            )
        )
    assert '"memories"' in result
    assert '"conversation"' in result


# ---------------------------------------------------------------------------
# _build_system_context_string_async
# ---------------------------------------------------------------------------


def test_build_system_context_string_async_minimal():
    db = MagicMock()
    with patch.object(ai_coach, "_summarize_training_load", return_value={}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={}
    ), patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={"timezone_offset_min": 0}
    ), patch.object(ai_coach, "recent_workouts_teaser", return_value=[]):
        result = _run_async(
            ai_coach._build_system_context_string_async(db, "ath-1", query=None, conversation_id=None)
        )
    assert "SYSTEM CONTEXT" in result
    assert '"recent_workouts"' not in result


def test_build_system_context_string_async_with_query_and_recent_workouts():
    db = MagicMock()
    with patch.object(ai_coach, "_summarize_training_load", return_value={}), patch.object(
        ai_coach, "_summarize_biometrics", return_value={}
    ), patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={"timezone_offset_min": 0}
    ), patch.object(
        ai_coach, "retrieve_relevant_memories", return_value=[{"content": "x", "created_at": "t"}]
    ), patch.object(
        ai_coach, "recent_workouts_teaser", return_value=[{"sport": "run"}]
    ), patch.object(
        ai_coach, "_load_conversation_history", return_value=[]
    ):
        result = _run_async(
            ai_coach._build_system_context_string_async(
                db, "ath-1", query="how was my run", conversation_id="conv-1"
            )
        )
    assert '"recent_workouts"' in result
    assert '"memories"' in result
    assert '"conversation"' in result


# ---------------------------------------------------------------------------
# get_coach_response_stream
# ---------------------------------------------------------------------------


def _sse_chunk(text):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(function_call=None, function_response=None, text=text, thought=False)]
                )
            )
        ],
        text=None,
    )


def test_get_coach_response_stream_yields_chunks_without_db():
    with patch.object(
        ai_coach._client.models,
        "generate_content_stream",
        return_value=[_sse_chunk("<response>Nice work today!</response>")],
    ):
        async def _run():
            chunks = []
            async for chunk in ai_coach.get_coach_response_stream("ath-1", "hi", db=None):
                chunks.append(chunk)
            return chunks

        result = _run_async(_run())
    assert "".join(result) == "Nice work today!"


def test_get_coach_response_stream_uses_db_context_when_present():
    db = MagicMock()
    with patch.object(
        ai_coach, "_build_system_context_string_async", return_value="[SYSTEM CONTEXT]..."
    ) as mock_ctx, patch.object(
        ai_coach._client.models,
        "generate_content_stream",
        return_value=[_sse_chunk("<response>Context-aware reply.</response>")],
    ):
        async def _run():
            chunks = []
            async for chunk in ai_coach.get_coach_response_stream("ath-1", "hi", db=db):
                chunks.append(chunk)
            return chunks

        result = _run_async(_run())
    mock_ctx.assert_awaited_once()
    assert "".join(result) == "Context-aware reply."


def test_get_coach_response_stream_thinking_model_sets_thinking_config():
    captured = {}

    def _fake_stream(*, model, contents, config):
        captured["config"] = config
        return [_sse_chunk("<response>ok</response>")]

    with patch.object(ai_coach._client.models, "generate_content_stream", side_effect=_fake_stream):
        async def _run():
            chunks = []
            async for chunk in ai_coach.get_coach_response_stream(
                "ath-1", "hi", db=None, model_name="gemini-3.5-thinking"
            ):
                chunks.append(chunk)
            return chunks

        _run_async(_run())
    assert captured["config"].thinking_config is not None


def test_get_coach_response_stream_empty_reply_yields_nothing():
    with patch.object(
        ai_coach._client.models, "generate_content_stream", return_value=[_sse_chunk("")]
    ):
        async def _run():
            chunks = []
            async for chunk in ai_coach.get_coach_response_stream("ath-1", "hi", db=None):
                chunks.append(chunk)
            return chunks

        result = _run_async(_run())
    assert result == []


# ---------------------------------------------------------------------------
# generate_coach_conversation_title
# ---------------------------------------------------------------------------


def test_generate_coach_conversation_title_empty_transcript_returns_new_chat():
    db = MagicMock()
    with patch.object(ai_coach, "_load_conversation_history", return_value=[]):
        result = ai_coach.generate_coach_conversation_title(db, "ath-1", "conv-1")
    assert result == "New chat"


def test_generate_coach_conversation_title_success():
    db = MagicMock()
    rows = [{"role": "user", "content": "How should I taper for my marathon?"}]
    with patch.object(ai_coach, "_load_conversation_history", return_value=rows), patch.object(
        ai_coach._client.models, "generate_content", return_value=SimpleNamespace(text="Marathon Taper Plan")
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        result = ai_coach.generate_coach_conversation_title(db, "ath-1", "conv-1")
    assert result == "Marathon Taper Plan"


def test_generate_coach_conversation_title_falls_back_when_title_too_short():
    db = MagicMock()
    rows = [{"role": "user", "content": "How should I taper for my marathon race next month"}]
    with patch.object(ai_coach, "_load_conversation_history", return_value=rows), patch.object(
        ai_coach._client.models, "generate_content", return_value=SimpleNamespace(text="Hi")
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        result = ai_coach.generate_coach_conversation_title(db, "ath-1", "conv-1")
    assert result.startswith("How should I taper")


def test_generate_coach_conversation_title_falls_back_on_exception():
    db = MagicMock()
    rows = [{"role": "user", "content": "How should I taper for my marathon race next month"}]
    with patch.object(ai_coach, "_load_conversation_history", return_value=rows), patch.object(
        ai_coach._client.models, "generate_content", side_effect=RuntimeError("boom")
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        result = ai_coach.generate_coach_conversation_title(db, "ath-1", "conv-1")
    assert result.startswith("How should I taper")
