from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import coach_tools


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_iso_date_requires_value():
    with pytest.raises(ValueError):
        coach_tools._parse_iso_date("")
    with pytest.raises(ValueError):
        coach_tools._parse_iso_date(None)


def test_parse_iso_date_parses_valid_string():
    assert coach_tools._parse_iso_date("2026-05-20") == date(2026, 5, 20)


def test_safe_float_and_safe_int():
    assert coach_tools._safe_float(None) is None
    assert coach_tools._safe_float("abc") is None
    assert coach_tools._safe_float("3.5") == 3.5
    assert coach_tools._safe_int(None) is None
    assert coach_tools._safe_int("abc") is None
    assert coach_tools._safe_int("42") == 42


def test_fetch_tss_history_rows_returns_error_dict_on_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.side_effect = (
        RuntimeError("db down")
    )
    rows = coach_tools._fetch_tss_history_rows(db, "athlete-1", today=date(2026, 5, 20))
    assert rows[0]["_error"] == "db down"


# ---------------------------------------------------------------------------
# handle_simulate_training_impact -- validation branches only (avoid the
# pre-existing date-sensitive projection-math flake in test_coach_tools.py).
# ---------------------------------------------------------------------------


def test_handle_simulate_training_impact_invalid_target_tss():
    db = MagicMock()
    result = coach_tools.handle_simulate_training_impact(
        {"target_tss": "abc", "target_date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert "error" in result


def test_handle_simulate_training_impact_negative_target_tss():
    db = MagicMock()
    result = coach_tools.handle_simulate_training_impact(
        {"target_tss": -5, "target_date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert "non-negative" in result["error"]


def test_handle_simulate_training_impact_invalid_date():
    db = MagicMock()
    result = coach_tools.handle_simulate_training_impact(
        {"target_tss": 50, "target_date": "not-a-date"}, athlete_id="athlete-1", db=db
    )
    assert "invalid target_date" in result["error"]


def test_handle_simulate_training_impact_rejects_past_date():
    db = MagicMock()
    with patch.object(coach_tools, "athlete_local_date", return_value=date(2026, 5, 20)):
        result = coach_tools.handle_simulate_training_impact(
            {"target_tss": 50, "target_date": "2026-05-01"}, athlete_id="athlete-1", db=db
        )
    assert "today or in the future" in result["error"]


def test_handle_simulate_training_impact_propagates_history_error():
    db = MagicMock()
    with patch.object(coach_tools, "athlete_local_date", return_value=date(2026, 5, 20)), patch.object(
        coach_tools, "_fetch_tss_history_rows", return_value=[{"_error": "db down"}]
    ):
        result = coach_tools.handle_simulate_training_impact(
            {"target_tss": 50, "target_date": "2026-05-20"}, athlete_id="athlete-1", db=db
        )
    assert result["error"] == "db down"


def test_handle_simulate_training_impact_success_shape():
    db = MagicMock()
    with patch.object(coach_tools, "athlete_local_date", return_value=date(2026, 5, 20)), patch.object(
        coach_tools, "_fetch_tss_history_rows", return_value=[{"date": "2026-05-19", "daily_tss": 40.0}]
    ):
        result = coach_tools.handle_simulate_training_impact(
            {"target_tss": 50, "target_date": "2026-05-20"}, athlete_id="athlete-1", db=db
        )
    assert "projected_ctl" in result
    assert result["days_out"] == 0
    assert result["today_tss_assumed"] == 50


# ---------------------------------------------------------------------------
# _workout_structure / _workout_structure_bodyweight
# ---------------------------------------------------------------------------


def test_workout_structure_bodyweight_mobility_without_hr_anchors():
    result = coach_tools._workout_structure_bodyweight("Endurance", 45, None, None, None, "mobility")
    assert result["sport"] == "mobility"
    assert all(block["target_hr"] is None for block in result["structure"])


def test_workout_structure_bodyweight_strength_with_hr_anchors():
    result = coach_tools._workout_structure_bodyweight("Threshold", 60, 165, 190, 50, "strength")
    assert result["sport"] == "strength"
    assert result["structure"][1]["target_hr"] is not None


def test_workout_structure_dispatches_to_bodyweight_for_mobility_and_strength():
    result = coach_tools._workout_structure("Endurance", 30, 250, 165, 190, 50, "mobility")
    assert result["sport"] == "mobility"


def test_workout_structure_power_based_for_bike():
    result = coach_tools._workout_structure("Threshold", 60, 250, 165, 190, 50, "bike")
    assert result["sport"] == "bike"
    assert len(result["structure"]) == 3


def test_workout_structure_hr_band_none_without_anchors():
    result = coach_tools._workout_structure("Endurance", 45, 250, None, None, None, "run")
    assert all(block["target_hr"] is None for block in result["structure"])


# ---------------------------------------------------------------------------
# _sanitize_workout_structure
# ---------------------------------------------------------------------------


def test_sanitize_workout_structure_returns_empty_for_non_list():
    assert coach_tools._sanitize_workout_structure(None) == []
    assert coach_tools._sanitize_workout_structure("not-a-list") == []


def test_sanitize_workout_structure_normalizes_legacy_fields():
    raw = [
        {"phase": "warmup", "duration_min": "10", "target_power_percent_ftp": "65"},
        "not-a-dict",
        {
            "name": "main",
            "duration": 20,
            "sub_intervals": [{"type": "work", "duration_min": "3", "target_hr_zone": "4"}, "bad"],
        },
    ]
    result = coach_tools._sanitize_workout_structure(raw)
    assert len(result) == 2
    assert result[0]["name"] == "Warmup"
    assert result[0]["duration_minutes"] == 10
    assert result[0]["target_power_percent_ftp"] == 65
    assert result[1]["sub_intervals"][0]["name"] == "Work"


def test_sanitize_workout_structure_handles_bad_duration_gracefully():
    raw = [{"name": "step", "duration_minutes": "not-a-number"}]
    result = coach_tools._sanitize_workout_structure(raw)
    assert result[0]["duration_minutes"] == 0


# ---------------------------------------------------------------------------
# handle_schedule_workout
# ---------------------------------------------------------------------------


def test_handle_schedule_workout_invalid_focus_zone():
    db = MagicMock()
    result = coach_tools.handle_schedule_workout({"focus_zone": "Nonsense"}, athlete_id="athlete-1", db=db)
    assert "error" in result


def test_handle_schedule_workout_invalid_duration_type():
    db = MagicMock()
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": "abc"}, athlete_id="athlete-1", db=db
    )
    assert "must be an integer" in result["error"]


def test_handle_schedule_workout_duration_out_of_range():
    db = MagicMock()
    result = coach_tools.handle_schedule_workout({"duration_minutes": 700}, athlete_id="athlete-1", db=db)
    assert "between 0 and 600" in result["error"]


def test_handle_schedule_workout_invalid_date():
    db = MagicMock()
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 30, "date": "garbage"}, athlete_id="athlete-1", db=db
    )
    assert "invalid date" in result["error"]


def test_handle_schedule_workout_athlete_query_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        RuntimeError("db down")
    )
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 30, "date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert "athlete_query_failed" in result["error"]


def test_handle_schedule_workout_zero_duration_rest_day():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={}
    )
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "p1"}])
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 0, "date": "2026-05-20", "sport": "run"}, athlete_id="athlete-1", db=db
    )
    assert result["target_tss_estimate"] == 0.0
    assert "Rest" in result["title"]


def test_handle_schedule_workout_insert_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={}
    )
    db.table.return_value.insert.return_value.execute.side_effect = RuntimeError("insert failed")
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 30, "date": "2026-05-20", "sport": "bike"}, athlete_id="athlete-1", db=db
    )
    assert "training_plans_insert_failed" in result["error"]


def test_handle_schedule_workout_success_with_ai_structure_override():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"ftp_watts": 250, "threshold_hr": 165, "max_hr": 190, "resting_hr": 50}
    )
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "p1"}])
    result = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 60,
            "date": "2026-05-20",
            "sport": "cycling",
            "focus_zone": "Threshold",
            "structure": [{"phase": "Warmup", "duration_minutes": 10}],
        },
        athlete_id="athlete-1",
        db=db,
    )
    assert result["training_plan_id"] == "p1"
    assert result["workout"]["structure"][0]["name"] == "Warmup"


def test_handle_schedule_workout_sport_alias_normalization():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={}
    )
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "p1"}])
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 30, "date": "2026-05-20", "sport": "jogging"}, athlete_id="athlete-1", db=db
    )
    assert result["workout"]["sport"] == "run"


# ---------------------------------------------------------------------------
# handle_calculate_nutrition
# ---------------------------------------------------------------------------


def test_handle_calculate_nutrition_invalid_duration_type():
    db = MagicMock()
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": "abc"}, athlete_id="athlete-1", db=db
    )
    assert "error" in result


def test_handle_calculate_nutrition_invalid_tss_type():
    db = MagicMock()
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_tss": "abc"}, athlete_id="athlete-1", db=db
    )
    assert "error" in result


def test_handle_calculate_nutrition_rejects_non_positive_duration():
    db = MagicMock()
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": 0}, athlete_id="athlete-1", db=db
    )
    assert "positive" in result["error"]


def test_handle_calculate_nutrition_rejects_negative_tss():
    db = MagicMock()
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": 60, "estimated_tss": -5}, athlete_id="athlete-1", db=db
    )
    assert "non-negative" in result["error"]


def test_handle_calculate_nutrition_swallows_ctl_query_errors():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = (
        RuntimeError("db down")
    )
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": 60, "estimated_tss": 50}, athlete_id="athlete-1", db=db
    )
    assert result["ctl_proxy"] == 0.0


@pytest.mark.parametrize(
    "duration,tss,expected_min_carb",
    [
        (45, 30, 0.0),  # short & easy -> no carbs
        (90, 50, 60.0),  # under 2h
        (150, 50, 80.0),  # under 3h
        (200, 50, 90.0),  # over 3h
    ],
)
def test_handle_calculate_nutrition_carb_brackets(duration, tss, expected_min_carb):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": duration, "estimated_tss": tss}, athlete_id="athlete-1", db=db
    )
    assert result["carb_g_per_hour"] == expected_min_carb


def test_handle_calculate_nutrition_high_intensity_bumps_carbs():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    result = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": 90, "estimated_tss": 120}, athlete_id="athlete-1", db=db
    )
    assert result["carb_g_per_hour"] == 80.0


# ---------------------------------------------------------------------------
# handle_save_memory / handle_update_memory / handle_list_memories
# ---------------------------------------------------------------------------


def test_handle_save_memory_requires_content():
    db = MagicMock()
    result = coach_tools.handle_save_memory({"content": "  "}, athlete_id="athlete-1", db=db)
    assert result["error"] == "content is required"


def test_handle_save_memory_success():
    db = MagicMock()
    with patch("app.services.memory.save_coach_memory") as mock_save:
        result = coach_tools.handle_save_memory({"content": "Race in June"}, athlete_id="athlete-1", db=db)
    assert result["status"] == "saved"
    mock_save.assert_called_once()


def test_handle_save_memory_returns_error_on_exception():
    db = MagicMock()
    with patch("app.services.memory.save_coach_memory", side_effect=RuntimeError("db down")):
        result = coach_tools.handle_save_memory({"content": "fact"}, athlete_id="athlete-1", db=db)
    assert result["error"] == "db down"


def test_handle_update_memory_requires_memory_id():
    db = MagicMock()
    result = coach_tools.handle_update_memory({}, athlete_id="athlete-1", db=db)
    assert result["error"] == "memory_id is required"


def test_handle_update_memory_requires_fields():
    db = MagicMock()
    result = coach_tools.handle_update_memory({"memory_id": "m1"}, athlete_id="athlete-1", db=db)
    assert result["error"] == "No fields to update"


def test_handle_update_memory_success():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "m1"}]
    )
    result = coach_tools.handle_update_memory(
        {"memory_id": "m1", "content": "updated"}, athlete_id="athlete-1", db=db
    )
    assert result["status"] == "success"


def test_handle_update_memory_retries_on_schema_drift():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = [
        RuntimeError("column coach_memories.event_date does not exist"),
        SimpleNamespace(data=[{"id": "m1"}]),
    ]
    result = coach_tools.handle_update_memory(
        {"memory_id": "m1", "content": "updated", "event_date": "2026-06-01"}, athlete_id="athlete-1", db=db
    )
    assert result["status"] == "partial_success"
    assert "event_date" in result["dropped_fields"]


def test_handle_update_memory_schema_drift_retry_fails_too():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = [
        RuntimeError("column coach_memories.event_date does not exist"),
        RuntimeError("still broken"),
    ]
    # "content" survives the schema-drift field drop, so the retry actually fires.
    result = coach_tools.handle_update_memory(
        {"memory_id": "m1", "content": "updated", "event_date": "2026-06-01"}, athlete_id="athlete-1", db=db
    )
    assert result["error"] == "still broken"


def test_handle_update_memory_unrelated_error_returned_directly():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "connection refused"
    )
    result = coach_tools.handle_update_memory({"memory_id": "m1", "content": "x"}, athlete_id="athlete-1", db=db)
    assert result["error"] == "connection refused"


def test_handle_list_memories_delegates():
    db = MagicMock()
    with patch("app.services.memory.list_coach_memories", return_value=[{"id": "m1"}]) as mock_list:
        result = coach_tools.handle_list_memories({"limit": 10}, athlete_id="athlete-1", db=db)
    assert result["memories"] == [{"id": "m1"}]
    mock_list.assert_called_once()


# ---------------------------------------------------------------------------
# handle_clear_training_plans
# ---------------------------------------------------------------------------


def test_handle_clear_training_plans_invalid_start_date():
    db = MagicMock()
    result = coach_tools.handle_clear_training_plans(
        {"start_date": "bad", "end_date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert "invalid start_date" in result["error"]


def test_handle_clear_training_plans_invalid_end_date():
    db = MagicMock()
    result = coach_tools.handle_clear_training_plans(
        {"start_date": "2026-05-20", "end_date": "bad"}, athlete_id="athlete-1", db=db
    )
    assert "invalid end_date" in result["error"]


def test_handle_clear_training_plans_end_before_start():
    db = MagicMock()
    result = coach_tools.handle_clear_training_plans(
        {"start_date": "2026-05-20", "end_date": "2026-05-01"}, athlete_id="athlete-1", db=db
    )
    assert "end_date must be >= start_date" in result["error"]


def test_handle_clear_training_plans_success():
    db = MagicMock()
    db.table.return_value.delete.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "p1"}, {"id": "p2"}]
    )
    result = coach_tools.handle_clear_training_plans(
        {"start_date": "2026-05-01", "end_date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert result["status"] == "success"
    assert result["deleted"] == 2


def test_handle_clear_training_plans_delete_failure():
    db = MagicMock()
    db.table.return_value.delete.return_value.eq.return_value.gte.return_value.lte.return_value.execute.side_effect = (
        RuntimeError("db down")
    )
    result = coach_tools.handle_clear_training_plans(
        {"start_date": "2026-05-01", "end_date": "2026-05-20"}, athlete_id="athlete-1", db=db
    )
    assert "training_plans_delete_failed" in result["error"]


# ---------------------------------------------------------------------------
# Thin delegation handlers
# ---------------------------------------------------------------------------


def test_handle_list_workouts_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "list_workouts_compact", return_value={"count": 0}) as mock_fn:
        result = coach_tools.handle_list_workouts({}, athlete_id="athlete-1", db=db)
    assert result == {"count": 0}
    mock_fn.assert_called_once_with(db, "athlete-1", {})


def test_handle_get_workout_summary_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "get_workout_summary", return_value={"id": "w1"}) as mock_fn:
        result = coach_tools.handle_get_workout_summary({"workout_id": "w1"}, athlete_id="athlete-1", db=db)
    assert result == {"id": "w1"}
    mock_fn.assert_called_once()


def test_handle_log_workout_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "log_workout_sync", return_value={"status": "created"}):
        result = coach_tools.handle_log_workout({}, athlete_id="athlete-1", db=db)
    assert result == {"status": "created"}


def test_handle_update_workout_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "update_workout_sync", return_value={"status": "updated"}):
        result = coach_tools.handle_update_workout({}, athlete_id="athlete-1", db=db)
    assert result == {"status": "updated"}


def test_handle_log_biometrics_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "log_biometrics_sync", return_value={"status": "saved"}):
        result = coach_tools.handle_log_biometrics({}, athlete_id="athlete-1", db=db)
    assert result == {"status": "saved"}


def test_handle_get_athlete_zones_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "get_athlete_zones_payload", return_value={"zones": []}):
        result = coach_tools.handle_get_athlete_zones({}, athlete_id="athlete-1", db=db)
    assert result == {"zones": []}


def test_handle_update_planned_workout_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "update_planned_workout_sync", return_value={"status": "updated"}):
        result = coach_tools.handle_update_planned_workout({}, athlete_id="athlete-1", db=db)
    assert result == {"status": "updated"}


def test_handle_delete_planned_workout_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "delete_planned_workout_sync", return_value={"status": "deleted"}):
        result = coach_tools.handle_delete_planned_workout({}, athlete_id="athlete-1", db=db)
    assert result == {"status": "deleted"}


def test_handle_list_planned_workouts_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "list_planned_workouts_compact", return_value={"count": 0}):
        result = coach_tools.handle_list_planned_workouts({}, athlete_id="athlete-1", db=db)
    assert result == {"count": 0}


def test_handle_get_training_load_series_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "get_training_load_series", return_value={"count": 0}):
        result = coach_tools.handle_get_training_load_series({}, athlete_id="athlete-1", db=db)
    assert result == {"count": 0}


def test_handle_get_biometrics_for_dates_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "get_biometrics_for_dates", return_value={"count": 0}):
        result = coach_tools.handle_get_biometrics_for_dates({}, athlete_id="athlete-1", db=db)
    assert result == {"count": 0}


def test_handle_summarize_workouts_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "summarize_workouts", return_value={"workout_count": 0}):
        result = coach_tools.handle_summarize_workouts({}, athlete_id="athlete-1", db=db)
    assert result == {"workout_count": 0}


def test_handle_compare_workouts_delegates():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "compare_workouts", return_value={"a": 1}):
        result = coach_tools.handle_compare_workouts({}, athlete_id="athlete-1", db=db)
    assert result == {"a": 1}


def test_handle_get_workout_streams_window_resolves_workout_by_date_when_no_id():
    db = MagicMock()
    with patch.object(
        coach_tools.workout_data, "resolve_workout_row", return_value={"id": "w1"}
    ), patch.object(coach_tools.workout_data, "slice_stream_window", return_value={"metrics": {}}) as mock_slice:
        result = coach_tools.handle_get_workout_streams_window(
            {"on_date": "2026-05-20", "sport": "run"}, athlete_id="athlete-1", db=db
        )
    assert result == {"metrics": {}}
    mock_slice.assert_called_once()


def test_handle_get_workout_streams_window_not_found():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "resolve_workout_row", return_value=None):
        result = coach_tools.handle_get_workout_streams_window({}, athlete_id="athlete-1", db=db)
    assert result == {"error": "workout_not_found"}


def test_handle_get_workout_streams_window_center_and_window():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "slice_stream_window", return_value={}) as mock_slice:
        coach_tools.handle_get_workout_streams_window(
            {"workout_id": "w1", "center_min": 10, "window_min": 4}, athlete_id="athlete-1", db=db
        )
    _, kwargs = mock_slice.call_args
    assert kwargs["start_offset_min"] == 8.0
    assert kwargs["end_offset_min"] == 12.0


def test_handle_get_workout_streams_window_invalid_offsets():
    db = MagicMock()
    result = coach_tools.handle_get_workout_streams_window(
        {"workout_id": "w1", "start_offset_min": "abc"}, athlete_id="athlete-1", db=db
    )
    assert result == {"error": "invalid offset minutes"}


def test_handle_get_workout_streams_window_normalizes_metrics_string():
    db = MagicMock()
    with patch.object(coach_tools.workout_data, "slice_stream_window", return_value={}) as mock_slice:
        coach_tools.handle_get_workout_streams_window(
            {"workout_id": "w1", "metrics": "hr"}, athlete_id="athlete-1", db=db
        )
    _, kwargs = mock_slice.call_args
    assert kwargs["metrics"] == ["hr"]


# ---------------------------------------------------------------------------
# handle_internal_scratchpad / parse_function_args
# ---------------------------------------------------------------------------


def test_handle_internal_scratchpad_always_succeeds():
    result = coach_tools.handle_internal_scratchpad({"thought": "planning..."}, athlete_id="athlete-1", db=MagicMock())
    assert result["status"] == "success"


def test_parse_function_args_none_returns_empty_dict():
    fc = SimpleNamespace(args=None)
    assert coach_tools.parse_function_args(fc) == {}


def test_parse_function_args_dict_passthrough():
    fc = SimpleNamespace(args={"a": 1})
    assert coach_tools.parse_function_args(fc) == {"a": 1}


def test_parse_function_args_json_string():
    fc = SimpleNamespace(args='{"a": 1}')
    assert coach_tools.parse_function_args(fc) == {"a": 1}


def test_parse_function_args_invalid_json_string_returns_empty():
    fc = SimpleNamespace(args="not-json")
    assert coach_tools.parse_function_args(fc) == {}


def test_parse_function_args_mapping_like_object():
    class _MappingLike:
        def keys(self):
            return ["a"]

        def __getitem__(self, key):
            return 1

    fc = SimpleNamespace(args=_MappingLike())
    assert coach_tools.parse_function_args(fc) == {"a": 1}


def test_parse_function_args_unconvertible_object_returns_empty():
    fc = SimpleNamespace(args=object())
    assert coach_tools.parse_function_args(fc) == {}


# ---------------------------------------------------------------------------
# Remaining scattered branch gaps
# ---------------------------------------------------------------------------


def test_handle_simulate_training_impact_skips_missing_and_unparseable_history_dates():
    # by_day-building loop inside handle_simulate_training_impact should skip rows
    # with a missing or unparseable date rather than raising.
    db = MagicMock()
    rows = [
        {"date": None, "daily_tss": 10},
        {"date": "not-a-date", "daily_tss": 20},
        {"date": "2026-05-19", "daily_tss": 30},
    ]
    with patch.object(coach_tools, "athlete_local_date", return_value=date(2026, 5, 20)), patch.object(
        coach_tools, "_fetch_tss_history_rows", return_value=rows
    ):
        result = coach_tools.handle_simulate_training_impact(
            {"target_tss": 50, "target_date": "2026-05-20"}, athlete_id="athlete-1", db=db
        )
    assert "projected_ctl" in result  # completed without raising on the bad rows


def test_sanitize_workout_structure_ignores_invalid_sub_interval_target_fields():
    raw = [
        {
            "name": "main",
            "duration_minutes": 20,
            "sub_intervals": [{"name": "work", "target_hr_zone": "not-a-number"}],
        }
    ]
    result = coach_tools._sanitize_workout_structure(raw)
    assert "target_hr_zone" not in result[0]["sub_intervals"][0]


def test_sanitize_workout_structure_ignores_invalid_top_level_target_fields():
    raw = [{"name": "main", "duration_minutes": 20, "target_power_percent_ftp": "not-a-number"}]
    result = coach_tools._sanitize_workout_structure(raw)
    assert "target_power_percent_ftp" not in result[0]


@pytest.mark.parametrize(
    "sport_input,expected",
    [("swimming", "swim"), ("erg", "row"), ("weights", "strength")],
)
def test_handle_schedule_workout_normalizes_additional_sport_aliases(sport_input, expected):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={}
    )
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "p1"}])
    result = coach_tools.handle_schedule_workout(
        {"duration_minutes": 30, "date": "2026-05-20", "sport": sport_input}, athlete_id="athlete-1", db=db
    )
    assert result["workout"]["sport"] == expected


def test_handle_update_memory_returns_original_error_when_no_fields_survive_drop():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "column coach_memories.event_date does not exist"
    )
    # Only event_date is provided, which gets dropped entirely by the schema-drift retry,
    # leaving nothing to retry with.
    result = coach_tools.handle_update_memory(
        {"memory_id": "m1", "event_date": "2026-06-01"}, athlete_id="athlete-1", db=db
    )
    assert "does not exist" in result["error"]
