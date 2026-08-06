from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.routers import analysis


# ---------------------------------------------------------------------------
# _parse_day
# ---------------------------------------------------------------------------


def test_parse_day_none_returns_today():
    assert analysis._parse_day(None) == date.today()


def test_parse_day_parses_iso_date():
    assert analysis._parse_day("2026-05-20") == date(2026, 5, 20)


def test_parse_day_truncates_to_date_portion():
    assert analysis._parse_day("2026-05-20T10:00:00Z") == date(2026, 5, 20)


# ---------------------------------------------------------------------------
# _baseline_30d
# ---------------------------------------------------------------------------


def test_baseline_30d_averages_valid_values():
    rows = [{"hrv": 50}, {"hrv": 60}, {"hrv": None}, {"hrv": 0}, {"hrv": "bad"}]
    assert analysis._baseline_30d(rows, "hrv") == 55.0


def test_baseline_30d_empty_returns_none():
    assert analysis._baseline_30d([], "hrv") is None
    assert analysis._baseline_30d([{"hrv": None}], "hrv") is None


# ---------------------------------------------------------------------------
# _zscore_for
# ---------------------------------------------------------------------------


def test_zscore_for_no_latest_or_no_rows_returns_none_triple():
    assert analysis._zscore_for([{"hrv": 50}], "hrv", None) == (None, None, None)
    assert analysis._zscore_for([], "hrv", 50) == (None, None, None)


def test_zscore_for_no_valid_history_returns_none_triple():
    rows = [{"hrv": None}, {"hrv": 0}]
    assert analysis._zscore_for(rows, "hrv", 50) == (None, None, None)


def test_zscore_for_computes_real_zscore():
    rows = [{"hrv": v} for v in [50, 58, 52, 60, 48, 56, 53]]
    z, mean, sd = analysis._zscore_for(rows, "hrv", 20.0)
    assert z is not None and z < -1  # sharp drop below a ~53-avg baseline
    assert mean is not None
    assert sd is not None


# ---------------------------------------------------------------------------
# _finite_recovery_score
# ---------------------------------------------------------------------------


def test_finite_recovery_score_none_row():
    assert analysis._finite_recovery_score(None) is None


def test_finite_recovery_score_missing_field():
    assert analysis._finite_recovery_score({}) is None


def test_finite_recovery_score_non_finite():
    assert analysis._finite_recovery_score({"recovery_score": float("nan")}) is None


def test_finite_recovery_score_valid():
    assert analysis._finite_recovery_score({"recovery_score": 72}) == 72.0


def test_finite_recovery_score_invalid_type_swallowed():
    assert analysis._finite_recovery_score({"recovery_score": "not-a-number"}) is None


# ---------------------------------------------------------------------------
# _fetch_timezone_offset_min
# ---------------------------------------------------------------------------


def test_fetch_timezone_offset_min_success():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"timezone_offset_min": -300}
    )
    assert analysis._fetch_timezone_offset_min(db, "ath-1") == -300


def test_fetch_timezone_offset_min_no_row_defaults_zero():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert analysis._fetch_timezone_offset_min(db, "ath-1") == 0


def test_fetch_timezone_offset_min_bad_value_defaults_zero():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"timezone_offset_min": "not-a-number"}
    )
    assert analysis._fetch_timezone_offset_min(db, "ath-1") == 0


# ---------------------------------------------------------------------------
# _row_wake_epoch_s
# ---------------------------------------------------------------------------


def test_row_wake_epoch_s_from_sleep_wakeup():
    row = {"sleep_wakeup": "2026-05-20T10:00:00Z"}
    result = analysis._row_wake_epoch_s(row, 0)
    assert result == datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc).timestamp()


def test_row_wake_epoch_s_naive_datetime_assumed_utc():
    row = {"sleep_wakeup": "2026-05-20T10:00:00"}
    result = analysis._row_wake_epoch_s(row, 0)
    assert result is not None


def test_row_wake_epoch_s_falls_back_to_date_field():
    row = {"date": "2026-05-20"}
    result = analysis._row_wake_epoch_s(row, 0)
    assert result is not None


def test_row_wake_epoch_s_no_usable_fields_returns_none():
    assert analysis._row_wake_epoch_s({}, 0) is None


def test_row_wake_epoch_s_bad_wakeup_falls_back_to_date():
    row = {"sleep_wakeup": "garbage", "date": "2026-05-20"}
    result = analysis._row_wake_epoch_s(row, 0)
    assert result is not None


# ---------------------------------------------------------------------------
# _resolve_current_recovery_state
# ---------------------------------------------------------------------------


def test_resolve_current_recovery_state_today_row_has_score():
    db = MagicMock()
    today_row = {"recovery_score": 70, "date": "2026-05-20", "sleep_wakeup": "2026-05-20T10:00:00Z"}
    result = analysis._resolve_current_recovery_state(db, "ath-1", date(2026, 5, 20), today_row, timezone_offset_min=0)
    assert result["has_today_row"] is True
    assert result["carried_forward"] is False
    assert result["effective_row"] == today_row


def test_resolve_current_recovery_state_carries_forward_when_missing():
    db = MagicMock()
    prior_row = {"recovery_score": 65, "date": "2026-05-18", "sleep_wakeup": "2026-05-18T10:00:00Z"}
    db.table.return_value.select.return_value.eq.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"recovery_score": None, "date": "2026-05-19"}, prior_row]
    )
    result = analysis._resolve_current_recovery_state(db, "ath-1", date(2026, 5, 20), None, timezone_offset_min=0)
    assert result["has_today_row"] is False
    assert result["carried_forward"] is True
    assert result["source_date"] == "2026-05-18"


def test_resolve_current_recovery_state_no_data_at_all():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    result = analysis._resolve_current_recovery_state(db, "ath-1", date(2026, 5, 20), None)
    assert result["effective_row"] is None
    assert result["is_stale"] is False
    assert result["age_hours"] is None


def test_resolve_current_recovery_state_stale_when_old():
    db = MagicMock()
    old_row = {"recovery_score": 65, "date": "2020-01-01", "sleep_wakeup": "2020-01-01T10:00:00Z"}
    result = analysis._resolve_current_recovery_state(db, "ath-1", date(2026, 5, 20), old_row, timezone_offset_min=0)
    assert result["is_stale"] is True
    assert result["age_hours"] > 36


# ---------------------------------------------------------------------------
# _biometrics_payload_for_context
# ---------------------------------------------------------------------------


def test_biometrics_payload_unavailable_when_stale():
    state = {"is_stale": True, "context_day": "2026-05-20", "effective_row": {"recovery_score": 50}}
    result = analysis._biometrics_payload_for_context({"recovery_score": 50}, state)
    assert result == {"available": False, "context_day": "2026-05-20"}


def test_biometrics_payload_unavailable_when_no_effective_row():
    state = {"is_stale": False, "context_day": "2026-05-20", "effective_row": None}
    assert analysis._biometrics_payload_for_context(None, state) == {
        "available": False,
        "context_day": "2026-05-20",
    }


def test_biometrics_payload_carried_forward_marks_context_day():
    effective = {"recovery_score": 60, "date": "2026-05-18"}
    state = {
        "is_stale": False,
        "carried_forward": True,
        "context_day": "2026-05-20",
        "effective_row": effective,
    }
    result = analysis._biometrics_payload_for_context(None, state)
    assert result["carried_forward"] is True
    assert result["context_day"] == "2026-05-20"
    assert result["recovery_score"] == 60


def test_biometrics_payload_fresh_today_row_passthrough():
    effective = {"recovery_score": 60}
    state = {"is_stale": False, "carried_forward": False, "context_day": "2026-05-20", "effective_row": effective}
    result = analysis._biometrics_payload_for_context(effective, state)
    assert "carried_forward" not in result
    assert result["recovery_score"] == 60


# ---------------------------------------------------------------------------
# _n / _fmt_num / _fmt_signed
# ---------------------------------------------------------------------------


def test_n_helper():
    assert analysis._n(None) is None
    assert analysis._n("42") == 42.0
    assert analysis._n("bad") is None


def test_fmt_num():
    assert analysis._fmt_num(None) == ""
    assert analysis._fmt_num(5.0) == "5"
    assert analysis._fmt_num(5.256, decimals=2) == "5.26"
    assert analysis._fmt_num(5.10, decimals=2) == "5.1"


def test_fmt_signed():
    assert analysis._fmt_signed(None) == ""
    assert analysis._fmt_signed(5.5) == "+5.5"
    assert analysis._fmt_signed(-5.5) == "-5.5"
    assert analysis._fmt_signed(0) == "+0"


# ---------------------------------------------------------------------------
# _strip_leading_time_of_day_greeting
# ---------------------------------------------------------------------------


def test_strip_leading_greeting_removes_and_capitalizes():
    assert analysis._strip_leading_time_of_day_greeting("Good morning, ready to train?") == "Ready to train?"


def test_strip_leading_greeting_none_input():
    assert analysis._strip_leading_time_of_day_greeting(None) == ""


def test_strip_leading_greeting_no_match_unchanged():
    assert analysis._strip_leading_time_of_day_greeting("How's it going?") == "How's it going?"


# ---------------------------------------------------------------------------
# _strain_label
# ---------------------------------------------------------------------------


def test_strain_label_bands():
    assert analysis._strain_label(None) is None
    assert analysis._strain_label(20) == "light"
    assert analysis._strain_label(50) == "moderate"
    assert analysis._strain_label(80) == "high"


# ---------------------------------------------------------------------------
# _analysis_fingerprint
# ---------------------------------------------------------------------------


def test_analysis_fingerprint_uses_policy_version_when_present():
    fp_strain = analysis._analysis_fingerprint("strain", {"a": 1})
    fp_recovery = analysis._analysis_fingerprint("recovery", {"a": 1})
    assert fp_strain != fp_recovery  # strain has a policy version wrapper, recovery doesn't
    assert isinstance(fp_strain, str)


def test_analysis_fingerprint_deterministic_for_same_input():
    assert analysis._analysis_fingerprint("strain", {"a": 1}) == analysis._analysis_fingerprint("strain", {"a": 1})


# ---------------------------------------------------------------------------
# _violates_strain_policy
# ---------------------------------------------------------------------------


def test_violates_strain_policy_empty_text_is_violation():
    assert analysis._violates_strain_policy("", {}) is True


def test_violates_strain_policy_low_strain_forbidden_terms():
    ctx = {"biometrics": {"strain_score": 20}}
    assert analysis._violates_strain_policy("You handled a significant training load today.", ctx) is True


def test_violates_strain_policy_low_strain_clean_text_ok():
    ctx = {"biometrics": {"strain_score": 20}}
    assert analysis._violates_strain_policy("Today was a light and easy day.", ctx) is False


def test_violates_strain_policy_fresh_tsb_forbidden_terms():
    ctx = {"pmc": {"tsb": 5}}
    assert analysis._violates_strain_policy("You're in a productive overload phase.", ctx) is True


def test_violates_strain_policy_fresh_tsb_clean_text_ok():
    ctx = {"pmc": {"tsb": 5}}
    assert analysis._violates_strain_policy("You look fresh and ready to train.", ctx) is False


def test_violates_strain_policy_no_matching_conditions():
    assert analysis._violates_strain_policy("Anything goes here.", {}) is False


# ---------------------------------------------------------------------------
# _sanitize_analysis_content
# ---------------------------------------------------------------------------


def test_sanitize_strain_replaces_violating_text_with_fallback():
    ctx = {"biometrics": {"strain_score": 20}}
    result = analysis._sanitize_analysis_content("strain", ctx, "significant training load today")
    assert "significant training load" not in result


def test_sanitize_strain_leaves_clean_text_alone():
    ctx = {"biometrics": {"strain_score": 20}}
    text = "Today was light and easy."
    assert analysis._sanitize_analysis_content("strain", ctx, text) == text


def test_sanitize_dashboard_summary_strips_greeting():
    result = analysis._sanitize_analysis_content("dashboard_summary", {}, "Good morning, all set.")
    assert result == "All set."


def test_sanitize_other_types_passthrough():
    assert analysis._sanitize_analysis_content("recovery", {}, "some text") == "some text"


# ---------------------------------------------------------------------------
# _fallback_content -- one representative case per analysis_type, plus the
# "insufficient data" branch for each.
# ---------------------------------------------------------------------------


def test_fallback_content_time_in_zones_missing_data():
    result = analysis._fallback_content("time_in_zones", {})
    assert "missing heart-rate zone" in result


def test_fallback_content_time_in_zones_aerobic_dominant():
    ctx = {"zone_distribution": {"z1": 50, "z2": 30, "z3": 10, "z4": 5, "z5": 5}}
    result = analysis._fallback_content("time_in_zones", ctx)
    assert "aerobic" in result


def test_fallback_content_time_in_zones_high_intensity():
    ctx = {"zone_distribution": {"z1": 20, "z2": 20, "z3": 10, "z4": 30, "z5": 20}}
    result = analysis._fallback_content("time_in_zones", ctx)
    assert "high intensity load" in result


def test_fallback_content_time_in_zones_mixed():
    ctx = {"zone_distribution": {"z1": 20, "z2": 20, "z3": 40, "z4": 10, "z5": 10}}
    result = analysis._fallback_content("time_in_zones", ctx)
    assert "mixed" in result


def test_fallback_content_workout_missing_data():
    result = analysis._fallback_content("workout", {"sport": "run"})
    assert "key metrics" in result


def test_fallback_content_workout_full_data():
    ctx = {
        "sport": "run",
        "title": "Morning Run",
        "duration_secs": 3600,
        "tss": 60,
        "strain_score": 50,
        "avg_hr": 145,
        "max_hr": 172,
        "avg_power": 200,
        "distance_meters": 10000,
    }
    result = analysis._fallback_content("workout", ctx)
    assert "Morning Run" in result
    assert "moderate" in result


def test_fallback_content_workout_easy_effort_short_duration():
    ctx = {"sport": "run", "strain_score": 10, "duration_secs": 600}
    result = analysis._fallback_content("workout", ctx)
    assert "easy" in result
    assert "recovery day" in result


def test_fallback_content_dashboard_summary_no_data():
    result = analysis._fallback_content("dashboard_summary", {})
    assert "haven't synced" in result


def test_fallback_content_dashboard_summary_stale():
    ctx = {
        "biometrics": {
            "biometrics": {"available": False},
            "current_recovery_state": {"is_stale": True},
        }
    }
    result = analysis._fallback_content("dashboard_summary", ctx)
    assert "older recovery data" in result


def test_fallback_content_dashboard_summary_fatigued():
    ctx = {
        "biometrics": {"biometrics": {"recovery_score": 20}},
        "training_load": {"current": {"tsb": -25}},
    }
    result = analysis._fallback_content("dashboard_summary", ctx)
    assert "fatigue" in result


def test_fallback_content_dashboard_summary_ready_to_train():
    ctx = {
        "biometrics": {"biometrics": {"recovery_score": 80}},
        "training_load": {"current": {"tsb": 0}},
    }
    result = analysis._fallback_content("dashboard_summary", ctx)
    assert "ready to train" in result


def test_fallback_content_training_load_no_data():
    result = analysis._fallback_content("training_load", {})
    assert "hasn't synced" in result


def test_fallback_content_training_load_high_fatigue():
    ctx = {"current": {"ctl": 50, "atl": 70, "tsb": -25}, "weekly_tss": 400}
    result = analysis._fallback_content("training_load", ctx)
    assert "high fatigue" in result


def test_fallback_content_training_load_fresh():
    ctx = {"current": {"ctl": 50, "atl": 30, "tsb": 15}, "weekly_tss": 300}
    result = analysis._fallback_content("training_load", ctx)
    assert "fresh" in result


def test_fallback_content_recovery_no_data():
    result = analysis._fallback_content("recovery", {})
    assert "missing" in result


def test_fallback_content_recovery_suppressed():
    ctx = {"biometrics": {"recovery_score": 20, "hrv_rmssd": 30}}
    result = analysis._fallback_content("recovery", ctx)
    assert "suppressed" in result


def test_fallback_content_recovery_strong():
    ctx = {"biometrics": {"recovery_score": 80}}
    result = analysis._fallback_content("recovery", ctx)
    assert "strong" in result


def test_fallback_content_sleep_no_data():
    result = analysis._fallback_content("sleep", {})
    assert "missing" in result


def test_fallback_content_sleep_poor():
    ctx = {"biometrics": {"sleep_score": 20, "sleep_duration_min": 300}}
    result = analysis._fallback_content("sleep", ctx)
    assert "poor" in result


def test_fallback_content_sleep_solid():
    ctx = {"biometrics": {"sleep_score": 80}}
    result = analysis._fallback_content("sleep", ctx)
    assert "solid" in result


def test_fallback_content_strain_no_data():
    result = analysis._fallback_content("strain", {})
    assert "missing" in result


def test_fallback_content_strain_high_fatigue_overrides_strain_level():
    ctx = {"biometrics": {"strain_score": 20}, "pmc": {"tsb": -25}}
    result = analysis._fallback_content("strain", ctx)
    assert "elevated fatigue" in result


def test_fallback_content_strain_light_with_good_form():
    ctx = {"biometrics": {"strain_score": 20, "recovery_score": 80}, "pmc": {"tsb": 0}}
    result = analysis._fallback_content("strain", ctx)
    assert "light" in result


def test_fallback_content_strain_high():
    ctx = {"biometrics": {"strain_score": 80}, "pmc": {}}
    result = analysis._fallback_content("strain", ctx)
    assert "High strain day" in result


def test_fallback_content_unknown_type_generic_message():
    result = analysis._fallback_content("something_else", {})
    assert "hasn't synced" in result
