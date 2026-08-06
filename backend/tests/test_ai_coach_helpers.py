from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import ai_coach


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def test_should_fallback_chat_model_true_variants():
    assert ai_coach._should_fallback_chat_model("503 Service Unavailable")
    assert ai_coach._should_fallback_chat_model("model is overloaded right now")
    assert ai_coach._should_fallback_chat_model("RESOURCE_EXHAUSTED: quota exceeded")


def test_should_fallback_chat_model_false():
    assert not ai_coach._should_fallback_chat_model("permission denied")
    assert not ai_coach._should_fallback_chat_model(None)


def test_load_coach_instructions_reads_file(tmp_path):
    prompt_file = tmp_path / "coach.md"
    prompt_file.write_text("You are the coach.", encoding="utf-8")
    with patch.object(ai_coach.settings, "PROMPTS_DIR", tmp_path), patch.object(
        ai_coach.settings, "COACH_PROMPT_FILE", "coach.md"
    ):
        assert ai_coach.load_coach_instructions() == "You are the coach."


def test_load_coach_instructions_missing_file_falls_back(tmp_path):
    with patch.object(ai_coach.settings, "PROMPTS_DIR", tmp_path), patch.object(
        ai_coach.settings, "COACH_PROMPT_FILE", "missing.md"
    ):
        result = ai_coach.load_coach_instructions()
    assert "ASTRAPHE" in result


def test_safe_float():
    assert ai_coach._safe_float("1.5") == 1.5
    assert ai_coach._safe_float(None) is None
    assert ai_coach._safe_float("not-a-number") is None


def test_safe_int():
    assert ai_coach._safe_int("5") == 5
    assert ai_coach._safe_int(None) is None
    assert ai_coach._safe_int("nope") is None


# ---------------------------------------------------------------------------
# _summarize_biometrics
# ---------------------------------------------------------------------------


def _bio_db(rows):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=rows
    )
    return db


def test_summarize_biometrics_no_rows():
    result = ai_coach._summarize_biometrics(_bio_db([]), "ath-1")
    assert result == {"available": False}


def test_summarize_biometrics_query_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    result = ai_coach._summarize_biometrics(db, "ath-1")
    assert "error" in result


def test_summarize_biometrics_with_rows_metric_units():
    rows = [
        {
            "date": "2026-05-20",
            "hrv_rmssd": 55.0,
            "resting_hr": 48,
            "sleep_duration_min": 420,
            "sleep_score": 80,
            "recovery_score": 70,
            "readiness_score": 75,
            "strain_score": 12.0,
            "spo2_pct": 97.0,
            "skin_temp": 33.5,
        },
        {
            "date": "2026-05-19",
            "hrv_rmssd": 50.0,
            "resting_hr": 50,
            "sleep_duration_min": 400,
            "sleep_score": 75,
            "recovery_score": 65,
            "readiness_score": 70,
            "strain_score": 10.0,
            "spo2_pct": 96.0,
            "skin_temp": 33.0,
        },
    ]
    result = ai_coach._summarize_biometrics(_bio_db(rows), "ath-1")
    assert result["available"] is True
    assert result["units"] == "Celsius (°C)"
    assert result["latest"]["hrv_rmssd"] == 55.0
    assert result["avg_7d"]["hrv_rmssd"] == 52.5
    assert "delta_vs_7d_avg" in result


def test_summarize_biometrics_imperial_units_converts_temp():
    rows = [{"date": "2026-05-20", "skin_temp": 0.0}]
    result = ai_coach._summarize_biometrics(_bio_db(rows), "ath-1", units="imperial")
    assert result["units"] == "Fahrenheit (°F)"
    assert result["latest"]["skin_temp"] == 32.0


# ---------------------------------------------------------------------------
# _summarize_training_load
# ---------------------------------------------------------------------------


def test_summarize_training_load_with_data():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"date": "2026-05-20", "daily_tss": 50.0, "ctl": 40.0, "atl": 45.0, "tsb": -5.0}]
    )
    result = ai_coach._summarize_training_load(db, "ath-1", current_tss=25.0)
    assert result["most_recent_workout_tss"] == 25.0
    assert result["latest_pmc"]["ctl"] == 40.0
    assert result["error"] is None


def test_summarize_training_load_no_data():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    result = ai_coach._summarize_training_load(db, "ath-1")
    assert result["latest_pmc"] is None
    assert result["most_recent_workout_tss"] == 0.0


def test_summarize_training_load_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = RuntimeError(
        "boom"
    )
    result = ai_coach._summarize_training_load(db, "ath-1")
    assert result["latest_pmc"] is None
    assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# _summarize_athlete_profile
# ---------------------------------------------------------------------------


def test_summarize_athlete_profile_with_data():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={
            "display_name": "Sean",
            "gender": "m",
            "timezone_offset_min": -300,
            "resting_hr": 48,
            "hrv_baseline": 55.0,
            "rhr_baseline": 47,
            "max_hr": 190,
            "threshold_hr": 165,
            "threshold_pace": "4:30",
            "measurement_units": "imperial",
        }
    )
    result = ai_coach._summarize_athlete_profile(db, "ath-1")
    assert result["display_name"] == "Sean"
    assert result["anchors"]["max_hr"] == 190
    assert result["measurement_units"] == "imperial"


def test_summarize_athlete_profile_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = RuntimeError(
        "db exploded"
    )
    result = ai_coach._summarize_athlete_profile(db, "ath-1")
    assert "error" in result


def test_summarize_athlete_profile_missing_row_defaults():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    result = ai_coach._summarize_athlete_profile(db, "ath-1")
    assert result["measurement_units"] == "metric"
    assert result["anchors"]["max_hr"] is None


# ---------------------------------------------------------------------------
# _load_conversation_history
# ---------------------------------------------------------------------------


def _history_db(rows):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=rows
    )
    return db


def test_load_conversation_history_orders_oldest_first_and_extracts_ai_text():
    rows = [
        {"role": "ai", "content": "<response>Hi there</response>", "image_urls": [], "created_at": "t2"},
        {"role": "user", "content": "hello", "image_urls": [], "created_at": "t1"},
    ]
    result = ai_coach._load_conversation_history(_history_db(rows), "ath-1", "conv-1")
    assert result[0]["content"] == "hello"
    assert result[1]["content"] == "Hi there"


def test_load_conversation_history_exception_returns_system_message():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = RuntimeError(
        "boom"
    )
    result = ai_coach._load_conversation_history(db, "ath-1", "conv-1")
    assert result[0]["role"] == "system"
    assert "boom" in result[0]["content"]


def test_load_conversation_history_clamps_limit():
    db = _history_db([])
    ai_coach._load_conversation_history(db, "ath-1", "conv-1", limit=9999)
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.assert_called_once_with(
        80
    )


# ---------------------------------------------------------------------------
# _get_context_parts_cached / invalidate_context_cache
# ---------------------------------------------------------------------------


def test_get_context_parts_cached_caches_between_calls():
    ai_coach.invalidate_context_cache("cache-test-athlete")
    db = MagicMock()
    with patch.object(ai_coach, "_summarize_biometrics", return_value={"available": False}) as mock_bio, patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={}):
        ai_coach._get_context_parts_cached(db, "cache-test-athlete")
        ai_coach._get_context_parts_cached(db, "cache-test-athlete")
    mock_bio.assert_called_once()
    ai_coach.invalidate_context_cache("cache-test-athlete")


def test_invalidate_context_cache_forces_refetch():
    ai_coach.invalidate_context_cache("cache-test-athlete-2")
    db = MagicMock()
    with patch.object(ai_coach, "_summarize_biometrics", return_value={"available": False}) as mock_bio, patch.object(
        ai_coach, "_summarize_athlete_profile", return_value={}
    ), patch.object(ai_coach, "_summarize_training_load", return_value={}):
        ai_coach._get_context_parts_cached(db, "cache-test-athlete-2")
        ai_coach.invalidate_context_cache("cache-test-athlete-2")
        ai_coach._get_context_parts_cached(db, "cache-test-athlete-2")
    assert mock_bio.call_count == 2


def test_invalidate_context_cache_missing_key_is_noop():
    ai_coach.invalidate_context_cache("never-cached-athlete")  # should not raise


# ---------------------------------------------------------------------------
# Time-of-day / calendar helpers
# ---------------------------------------------------------------------------


def test_time_of_day_greeting_morning():
    assert ai_coach._time_of_day_greeting(SimpleNamespace(hour=8)) == "Good morning"


def test_time_of_day_greeting_afternoon():
    assert ai_coach._time_of_day_greeting(SimpleNamespace(hour=14)) == "Good afternoon"


def test_time_of_day_greeting_evening():
    assert ai_coach._time_of_day_greeting(SimpleNamespace(hour=22)) == "Good evening"
    assert ai_coach._time_of_day_greeting(SimpleNamespace(hour=2)) == "Good evening"


def test_strip_leading_time_of_day_greeting_removes_and_capitalizes():
    result = ai_coach._strip_leading_time_of_day_greeting("Good morning, ready to train?")
    assert result == "Ready to train?"


def test_strip_leading_time_of_day_greeting_no_match_unchanged():
    assert ai_coach._strip_leading_time_of_day_greeting("How's it going?") == "How's it going?"


def test_strip_leading_time_of_day_greeting_empty_after_strip():
    assert ai_coach._strip_leading_time_of_day_greeting("Good evening") == ""


def test_strip_leading_time_of_day_greeting_none_input():
    assert ai_coach._strip_leading_time_of_day_greeting(None) == ""


def test_calendar_context_for_offset_shape():
    result = ai_coach._calendar_context_for_offset(0)
    assert "current_local_date" in result
    assert len(result["upcoming_weekdays"]) == 7


def test_athlete_local_calendar_uses_cached_profile_offset():
    db = MagicMock()
    with patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": -300}, {})
    ):
        result = ai_coach._athlete_local_calendar(db, "ath-1")
    assert "current_local_date" in result


def test_athlete_local_calendar_explicit_offset_overrides_profile():
    db = MagicMock()
    with patch.object(
        ai_coach, "_get_context_parts_cached", return_value=({}, {"timezone_offset_min": -300}, {})
    ):
        result = ai_coach._athlete_local_calendar(db, "ath-1", timezone_offset_min=60)
    assert "current_local_date" in result


# ---------------------------------------------------------------------------
# Relative-date / calendar-message helpers
# ---------------------------------------------------------------------------


def test_message_mentions_word_boundary():
    assert ai_coach._message_mentions("let's ride tomorrow", "tomorrow")
    assert not ai_coach._message_mentions("tomorrowland festival", "tomorrow")
    assert not ai_coach._message_mentions(None, "tomorrow")


def test_message_has_explicit_iso_date():
    assert ai_coach._message_has_explicit_iso_date("schedule it for 2026-05-20")
    assert not ai_coach._message_has_explicit_iso_date("schedule it for tomorrow")


def test_calendar_preface_includes_message_and_dates():
    calendar = ai_coach._calendar_context_for_offset(0)
    preface = ai_coach._calendar_preface("ride tomorrow please", calendar)
    assert "[ATHLETE-LOCAL CALENDAR]" in preface
    assert "ride tomorrow please" in preface


def test_normalize_relative_tool_dates_non_schedule_tool_passthrough():
    args = {"date": "whatever"}
    result = ai_coach._normalize_relative_tool_dates(
        "other_tool", args, message="tomorrow", calendar=ai_coach._calendar_context_for_offset(0)
    )
    assert result == args


def test_normalize_relative_tool_dates_explicit_iso_passthrough():
    calendar = ai_coach._calendar_context_for_offset(0)
    args = {"date": "2026-01-01"}
    result = ai_coach._normalize_relative_tool_dates(
        "schedule_workout", args, message="schedule for 2026-05-20", calendar=calendar
    )
    assert result == args


def test_normalize_relative_tool_dates_tomorrow():
    calendar = ai_coach._calendar_context_for_offset(0)
    result = ai_coach._normalize_relative_tool_dates(
        "schedule_workout", {}, message="ride tomorrow", calendar=calendar
    )
    assert result["date"] == calendar["tomorrow_date"]


def test_normalize_relative_tool_dates_today():
    calendar = ai_coach._calendar_context_for_offset(0)
    result = ai_coach._normalize_relative_tool_dates(
        "schedule_workout", {}, message="ride today please", calendar=calendar
    )
    assert result["date"] == calendar["current_local_date"]


def test_normalize_relative_tool_dates_weekday_match():
    calendar = ai_coach._calendar_context_for_offset(0)
    weekday = next(iter(calendar["upcoming_weekdays"]))
    result = ai_coach._normalize_relative_tool_dates(
        "schedule_workout", {}, message=f"ride on {weekday}", calendar=calendar
    )
    assert result["date"] == calendar["upcoming_weekdays"][weekday]


def test_normalize_relative_tool_dates_no_match_leaves_args_unchanged():
    calendar = ai_coach._calendar_context_for_offset(0)
    result = ai_coach._normalize_relative_tool_dates(
        "schedule_workout", {"date": "unset"}, message="ride sometime", calendar=calendar
    )
    assert result == {"date": "unset"}


def test_month_day_labels_valid_date():
    labels = ai_coach._month_day_labels("2026-05-01")
    assert labels == ["May 1", "May 1st"]


def test_month_day_labels_suffixes():
    assert ai_coach._month_day_labels("2026-05-02")[1].endswith("2nd")
    assert ai_coach._month_day_labels("2026-05-03")[1].endswith("3rd")
    assert ai_coach._month_day_labels("2026-05-11")[1].endswith("11th")
    assert ai_coach._month_day_labels("2026-05-21")[1].endswith("21st")


def test_month_day_labels_invalid_date_returns_empty():
    assert ai_coach._month_day_labels("not-a-date") == []


def test_calendar_tool_result_reminder_tomorrow():
    calendar = ai_coach._calendar_context_for_offset(0)
    reminder = ai_coach._calendar_tool_result_reminder([calendar["tomorrow_date"]], calendar)
    assert reminder is not None
    assert "is tomorrow" in reminder


def test_calendar_tool_result_reminder_today():
    calendar = ai_coach._calendar_context_for_offset(0)
    reminder = ai_coach._calendar_tool_result_reminder([calendar["current_local_date"]], calendar)
    assert "is today" in reminder


def test_calendar_tool_result_reminder_no_match_returns_none():
    calendar = ai_coach._calendar_context_for_offset(0)
    assert ai_coach._calendar_tool_result_reminder(["2000-01-01"], calendar) is None


def test_correct_relative_date_language_rewrites_today_to_tomorrow():
    calendar = ai_coach._calendar_context_for_offset(0)
    tomorrow = calendar["tomorrow_date"]
    text = "I've scheduled your ride for today."
    result = ai_coach._correct_relative_date_language(text, [tomorrow], calendar)
    assert "tomorrow" in result.lower()


def test_correct_relative_date_language_skips_non_tomorrow_dates():
    calendar = ai_coach._calendar_context_for_offset(0)
    text = "I've scheduled your ride for today."
    result = ai_coach._correct_relative_date_language(text, ["2000-01-01"], calendar)
    assert result == text


# ---------------------------------------------------------------------------
# Response text extraction
# ---------------------------------------------------------------------------


def test_history_to_gemini_contents_filters_and_maps_roles():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "ai", "content": "<response>hello there</response>"},
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": ""},
    ]
    contents = ai_coach._history_to_gemini_contents(history)
    assert len(contents) == 2
    assert contents[0].role == "user"
    assert contents[1].role == "model"


def test_history_to_gemini_contents_ai_message_that_extracts_empty_is_skipped():
    history = [{"role": "ai", "content": "<response></response>"}]
    # extraction of an empty <response> body yields the failure message, not empty,
    # so this should NOT be skipped -- verifies non-empty fallback behavior.
    contents = ai_coach._history_to_gemini_contents(history)
    assert len(contents) == 1


def test_extract_grounding_sources_no_candidates():
    assert ai_coach._extract_grounding_sources(SimpleNamespace(candidates=None)) == []


def test_extract_grounding_sources_no_grounding_metadata():
    cand = SimpleNamespace(grounding_metadata=None)
    assert ai_coach._extract_grounding_sources(SimpleNamespace(candidates=[cand])) == []


def test_extract_grounding_sources_with_chunks_dedupes():
    web1 = SimpleNamespace(title="Source A", uri="https://a.example.com")
    web2 = SimpleNamespace(title="Source A dup", uri="https://a.example.com")
    web3 = SimpleNamespace(title="Source B", url="https://b.example.com", uri=None)
    chunk1 = SimpleNamespace(web=web1)
    chunk2 = SimpleNamespace(web=web2)
    chunk3 = SimpleNamespace(web=web3)
    chunk_none = SimpleNamespace(web=None)
    gmd = SimpleNamespace(grounding_chunks=[chunk1, chunk2, chunk3, chunk_none])
    cand = SimpleNamespace(grounding_metadata=gmd)
    response = SimpleNamespace(candidates=[cand])
    sources = ai_coach._extract_grounding_sources(response)
    assert len(sources) == 2
    assert sources[0]["url"] == "https://a.example.com"


class _RaisingCandidatesResponse:
    """A plain object (not MagicMock) whose .candidates access raises.

    Deliberately not a MagicMock subclass/instance: setting a raising property on
    ``type(some_mock_instance)`` would mutate the shared MagicMock class itself and
    leak into every other MagicMock in the process.
    """

    text = None

    @property
    def candidates(self):
        raise RuntimeError("boom")


def test_extract_grounding_sources_exception_returns_partial():
    assert ai_coach._extract_grounding_sources(_RaisingCandidatesResponse()) == []


def test_extract_non_thought_text_from_response_joins_visible_text():
    part1 = SimpleNamespace(function_call=None, function_response=None, text="Hello ", thought=False)
    part2 = SimpleNamespace(function_call=None, function_response=None, text="world", thought=False)
    content = SimpleNamespace(parts=[part1, part2])
    candidate = SimpleNamespace(content=content)
    response = SimpleNamespace(candidates=[candidate], text=None)
    assert ai_coach._extract_non_thought_text_from_response(response) == "Hello world"


def test_extract_non_thought_text_from_response_skips_function_parts():
    part1 = SimpleNamespace(function_call={"name": "x"}, function_response=None, text=None, thought=False)
    content = SimpleNamespace(parts=[part1])
    candidate = SimpleNamespace(content=content)
    response = SimpleNamespace(candidates=[candidate], text="fallback text")
    assert ai_coach._extract_non_thought_text_from_response(response) == "fallback text"


def test_extract_non_thought_text_from_response_all_thought_falls_back_to_thoughts():
    part1 = SimpleNamespace(function_call=None, function_response=None, text="secret reasoning", thought=True)
    content = SimpleNamespace(parts=[part1])
    candidate = SimpleNamespace(content=content)
    response = SimpleNamespace(candidates=[candidate], text=None)
    assert ai_coach._extract_non_thought_text_from_response(response, allow_text_fallback=False) == "secret reasoning"


def test_extract_non_thought_text_from_response_no_structured_parts_uses_text():
    candidate = SimpleNamespace(content=None)
    response = SimpleNamespace(candidates=[candidate], text="plain reply")
    assert ai_coach._extract_non_thought_text_from_response(response) == "plain reply"


def test_extract_non_thought_text_from_response_exception_returns_empty():
    assert ai_coach._extract_non_thought_text_from_response(_RaisingCandidatesResponse()) == ""


def test_extract_athlete_message_from_model_output_delegates():
    response = SimpleNamespace(candidates=[], text="<response>Final answer</response>")
    assert ai_coach._extract_athlete_message_from_model_output(response) == "Final answer"


def test_is_failed_extraction_empty_and_failure_message():
    assert ai_coach._is_failed_extraction("")
    assert ai_coach._is_failed_extraction(ai_coach._EXTRACTION_FAILURE_MESSAGE)
    assert not ai_coach._is_failed_extraction("a real reply")


def test_looks_like_planning_dump_true():
    text = "* Trigger: low HRV\n* Goal: recover\n* Draft: rest today"
    assert ai_coach._looks_like_planning_dump(text)


def test_looks_like_planning_dump_false():
    assert not ai_coach._looks_like_planning_dump("Nice work on that ride!")
    assert not ai_coach._looks_like_planning_dump("")


def test_dedupe_repeated_suffix_short_text_unchanged():
    assert ai_coach._dedupe_repeated_suffix("short") == "short"


def test_dedupe_repeated_suffix_removes_repeat():
    prefix = "This is a fairly long coach reply that repeats itself verbatim. "
    text = prefix + prefix
    result = ai_coach._dedupe_repeated_suffix(text)
    assert result == prefix.strip()


def test_dedupe_repeated_suffix_no_repeat_returns_full_text():
    text = (
        "Yesterday's long run felt strong through the first ten miles, but the heat "
        "really started to bite by mile fourteen and pacing slipped noticeably after that."
    )
    assert ai_coach._dedupe_repeated_suffix(text) == text


def test_extract_draft_or_final_reply_with_draft_marker():
    text = "* Trigger: x\nDraft: Great ride today, keep it up!"
    assert ai_coach._extract_draft_or_final_reply(text) == "Great ride today, keep it up!"


def test_extract_draft_or_final_reply_no_marker_returns_empty():
    assert ai_coach._extract_draft_or_final_reply("just a plain reply") == ""


def test_extract_draft_or_final_reply_empty_input():
    assert ai_coach._extract_draft_or_final_reply("") == ""


def test_extract_athlete_message_from_text_empty():
    assert ai_coach._extract_athlete_message_from_text("") == ""
    assert ai_coach._extract_athlete_message_from_text(None) == ""


def test_extract_athlete_message_from_text_response_tag():
    result = ai_coach._extract_athlete_message_from_text("blah <response>Great job!</response>")
    assert result == "Great job!"


def test_extract_athlete_message_from_text_uses_last_response_tag():
    text = "<response>first</response> ignored <response>second</response>"
    assert ai_coach._extract_athlete_message_from_text(text) == "second"


def test_extract_athlete_message_from_text_draft_fallback():
    text = "* Trigger: low HRV\nDraft: Take it easy today, your HRV is low."
    result = ai_coach._extract_athlete_message_from_text(text)
    assert "Take it easy today" in result


def test_extract_athlete_message_from_text_plain_text_passthrough():
    result = ai_coach._extract_athlete_message_from_text("Just a normal athlete-facing reply.")
    assert result == "Just a normal athlete-facing reply."


# ---------------------------------------------------------------------------
# Agentic / title helpers
# ---------------------------------------------------------------------------


def test_agentic_max_tool_hops_scheduling_keywords():
    assert ai_coach._agentic_max_tool_hops("please schedule my ride") == 8
    assert ai_coach._agentic_max_tool_hops("plan my training week") == 8


def test_agentic_max_tool_hops_short_message_skips_rag():
    assert ai_coach._agentic_max_tool_hops("thanks") == 3


def test_agentic_max_tool_hops_default():
    assert ai_coach._agentic_max_tool_hops("how should I approach my next big race build with periodization?") == 5


def test_format_transcript_for_title_truncates_long_content():
    rows = [{"role": "user", "content": "x" * 600}]
    result = ai_coach._format_transcript_for_title(rows, max_chars=50)
    assert result.startswith("Athlete: ")
    assert len(result) < 600


def test_format_transcript_for_title_skips_empty_content():
    rows = [{"role": "user", "content": "   "}, {"role": "ai", "content": "hi"}]
    result = ai_coach._format_transcript_for_title(rows)
    assert result == "Coach: hi"


def test_format_transcript_for_title_limits_turns():
    rows = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
    result = ai_coach._format_transcript_for_title(rows, max_turns=3)
    assert result.count("\n") == 2


def test_sanitize_generated_title_strips_prefix():
    # str.strip(chars) only trims characters that sit at the true start/end of the
    # string, so a leading "Title: " (letters, not in the strip set) blocks any
    # boundary-quote stripping until *after* the "^title:\s*" prefix regex runs.
    assert ai_coach._sanitize_generated_title("Title: Recovery Ride Plan") == "Recovery Ride Plan"


def test_sanitize_generated_title_strips_boundary_quotes():
    assert ai_coach._sanitize_generated_title('"Recovery Ride Plan"') == "Recovery Ride Plan"


def test_sanitize_generated_title_truncates_long_titles():
    long_title = " ".join(["word"] * 30)
    result = ai_coach._sanitize_generated_title(long_title)
    assert len(result) <= 60


def test_sanitize_generated_title_empty_input():
    assert ai_coach._sanitize_generated_title("") == ""
    assert ai_coach._sanitize_generated_title(None) == ""


def test_fallback_title_from_history_uses_last_user_message():
    rows = [
        {"role": "ai", "content": "ignored"},
        {"role": "user", "content": "how was my ride yesterday and what should I do next"},
    ]
    result = ai_coach._fallback_title_from_history(rows)
    assert result.startswith("how was my ride yesterday")
    assert result.endswith("…")


def test_fallback_title_from_history_no_user_messages():
    rows = [{"role": "ai", "content": "hi"}]
    assert ai_coach._fallback_title_from_history(rows) == "New chat"


def test_fallback_title_from_history_skips_blank_user_messages():
    rows = [{"role": "user", "content": "   "}, {"role": "user", "content": "real question"}]
    assert ai_coach._fallback_title_from_history(rows) == "real question"
