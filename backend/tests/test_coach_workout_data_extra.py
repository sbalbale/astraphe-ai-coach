from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import coach_workout_data as cwd


# ---------------------------------------------------------------------------
# Generic fake DB
# ---------------------------------------------------------------------------


class _Query:
    def __init__(self, db, table_name, response):
        self.db = db
        self.table_name = table_name
        self._response = response
        self._update_payload = None
        self._deleted = False

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self._update_payload = payload
        self.db.updates.setdefault(self.table_name, []).append(payload)
        return self

    def delete(self):
        self._deleted = True
        self.db.deletes.append(self.table_name)
        return self

    def execute(self):
        if self._update_payload is not None:
            return SimpleNamespace(data=[self._update_payload])
        if self._deleted:
            return SimpleNamespace(data=[])
        if callable(self._response):
            return self._response()
        return self._response


class _Db:
    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.updates: dict[str, list] = {}
        self.deletes: list[str] = []

    def table(self, name):
        resp = self.responses.get(name, SimpleNamespace(data=None))
        return _Query(self, name, resp)


def _athlete_db(offset_min=0, **athlete_fields):
    return _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": offset_min, **athlete_fields}),
        }
    )


# ---------------------------------------------------------------------------
# parse_coach_date / normalize_coach_sport
# ---------------------------------------------------------------------------


def test_parse_coach_date_raises_without_default():
    with pytest.raises(ValueError):
        cwd.parse_coach_date(None)


def test_parse_coach_date_uses_default_when_blank():
    d = date(2026, 5, 20)
    assert cwd.parse_coach_date("  ", default=d) == d


def test_normalize_coach_sport_covers_all_branches():
    assert cwd.normalize_coach_sport("running") == "run"
    assert cwd.normalize_coach_sport("swimming") == "swim"
    assert cwd.normalize_coach_sport("erg") == "row"
    assert cwd.normalize_coach_sport("lifting") == "strength"
    assert cwd.normalize_coach_sport("yoga") == "mobility"
    assert cwd.normalize_coach_sport("something-else") == "other"


# ---------------------------------------------------------------------------
# resolve_local_start_utc / _parse_dt / _duration_secs
# ---------------------------------------------------------------------------


def test_resolve_local_start_utc_uses_explicit_time():
    db = _athlete_db()
    result = cwd.resolve_local_start_utc(db, "athlete-1", date(2026, 5, 20), "14:30")
    assert result.astimezone(timezone.utc).hour in (14, 15, 13)  # tz offset 0 -> exactly 14
    assert result.hour == 14
    assert result.minute == 30


def test_resolve_local_start_utc_defaults_to_noon_for_past_dates():
    db = _athlete_db()
    with patch.object(cwd, "athlete_local_date", return_value=date(2026, 5, 25)):
        result = cwd.resolve_local_start_utc(db, "athlete-1", date(2026, 5, 20), None)
    assert result.hour == 12


def test_resolve_local_start_utc_uses_current_time_for_today():
    db = _athlete_db()
    now = datetime(2026, 5, 20, 8, 45, tzinfo=timezone.utc)
    with patch.object(cwd, "athlete_local_date", return_value=date(2026, 5, 20)), patch.object(
        cwd, "athlete_local_datetime", return_value=now
    ):
        result = cwd.resolve_local_start_utc(db, "athlete-1", date(2026, 5, 20), None)
    assert result.hour == 8
    assert result.minute == 45


def test_parse_dt_handles_all_shapes():
    assert cwd._parse_dt(None) is None
    dt = datetime(2026, 5, 20)
    assert cwd._parse_dt(dt) is dt
    assert cwd._parse_dt("2026-05-20T10:00:00Z") is not None
    assert cwd._parse_dt("garbage") is None
    assert cwd._parse_dt(12345) is None


def test_duration_secs_prefers_explicit_and_falls_back():
    assert cwd._duration_secs({"duration_seconds": 100}) == 100
    assert cwd._duration_secs({"started_at": "2026-05-20T10:00:00Z", "ended_at": "2026-05-20T10:30:00Z"}) == 1800
    assert cwd._duration_secs({}) is None


# ---------------------------------------------------------------------------
# format_workout_summary interval_count
# ---------------------------------------------------------------------------


def test_format_workout_summary_includes_interval_count():
    row = {"id": "w1", "intervals": [{"a": 1}, {"a": 2}]}
    summary = cwd.format_workout_summary(row)
    assert summary["interval_count"] == 2


def test_format_workout_summary_omits_lap_count_when_none():
    summary = cwd.format_workout_summary({"id": "w1"})
    assert "lap_count" not in summary


# ---------------------------------------------------------------------------
# resolve_workout_row
# ---------------------------------------------------------------------------


def test_resolve_workout_row_by_id():
    db = _Db({"workouts": SimpleNamespace(data={"id": "w1"})})
    row = cwd.resolve_workout_row(db, "athlete-1", {"workout_id": "w1"})
    assert row == {"id": "w1"}


def test_resolve_workout_row_returns_none_without_date_or_sport():
    db = _Db()
    assert cwd.resolve_workout_row(db, "athlete-1", {}) is None
    assert cwd.resolve_workout_row(db, "athlete-1", {"on_date": "2026-05-20"}) is None


def test_resolve_workout_row_by_date_and_sport():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "workouts": SimpleNamespace(data=[{"id": "w2", "sport": "run"}]),
        }
    )
    row = cwd.resolve_workout_row(db, "athlete-1", {"on_date": "2026-05-20", "sport": "run"})
    assert row == {"id": "w2", "sport": "run"}


def test_resolve_workout_row_returns_none_when_no_matches():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "workouts": SimpleNamespace(data=[]),
        }
    )
    assert cwd.resolve_workout_row(db, "athlete-1", {"on_date": "2026-05-20", "sport": "run"}) is None


# ---------------------------------------------------------------------------
# _count_laps / get_workout_summary
# ---------------------------------------------------------------------------


def test_count_laps_returns_none_on_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    assert cwd._count_laps(db, "athlete-1", "w1") is None


def test_get_workout_summary_error_when_not_found():
    db = _Db()
    assert cwd.get_workout_summary(db, "athlete-1", {"workout_id": "w1"}) == {"error": "workout_not_found"}


# ---------------------------------------------------------------------------
# slice_stream_window
# ---------------------------------------------------------------------------


def test_slice_stream_window_invalid_window():
    db = _Db()
    result = cwd.slice_stream_window(db, "athlete-1", "w1", start_offset_min=5, end_offset_min=2)
    assert result["error"] == "invalid_window"


def test_slice_stream_window_too_large():
    db = _Db()
    result = cwd.slice_stream_window(db, "athlete-1", "w1", start_offset_min=0, end_offset_min=100)
    assert result["error"] == "window_too_large"


def test_slice_stream_window_unavailable_when_no_streams():
    db = _Db()
    with patch.object(cwd, "fetch_stream_row_columns", return_value=None):
        result = cwd.slice_stream_window(db, "athlete-1", "w1", start_offset_min=0, end_offset_min=5)
    assert result["error"] == "streams_unavailable"


def test_slice_stream_window_returns_metrics():
    row = {"time_series": {"heartrate": [140.0] * 600}, "resolution_seconds": 1}
    db = _Db()
    with patch.object(cwd, "fetch_stream_row_columns", return_value=row):
        result = cwd.slice_stream_window(
            db, "athlete-1", "w1", start_offset_min=0, end_offset_min=5, metrics=["hr", "unknown_metric"]
        )
    assert "hr" in result["metrics"]
    assert result["metrics"]["hr"]["min"] == 140.0


def test_slice_stream_window_unavailable_when_metric_series_empty():
    row = {"time_series": {"heartrate": []}, "resolution_seconds": 1}
    db = _Db()
    with patch.object(cwd, "fetch_stream_row_columns", return_value=row):
        result = cwd.slice_stream_window(db, "athlete-1", "w1", start_offset_min=0, end_offset_min=5)
    assert result["error"] == "streams_unavailable"


# ---------------------------------------------------------------------------
# fetch_athlete_ftp
# ---------------------------------------------------------------------------


def test_fetch_athlete_ftp_default_when_missing():
    db = _Db({"athletes": SimpleNamespace(data={})})
    assert cwd.fetch_athlete_ftp(db, "athlete-1") == 250


def test_fetch_athlete_ftp_returns_stored_value():
    db = _Db({"athletes": SimpleNamespace(data={"ftp_watts": 280})})
    assert cwd.fetch_athlete_ftp(db, "athlete-1") == 280


def test_fetch_athlete_ftp_default_on_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        RuntimeError("down")
    )
    assert cwd.fetch_athlete_ftp(db, "athlete-1") == 250


# ---------------------------------------------------------------------------
# build_log_workout_payload
# ---------------------------------------------------------------------------


def test_build_log_workout_payload_requires_sport():
    db = _athlete_db()
    with pytest.raises(ValueError, match="sport is required"):
        cwd.build_log_workout_payload(db, "athlete-1", {"duration_minutes": 30})


def test_build_log_workout_payload_rejects_invalid_duration():
    db = _athlete_db()
    with pytest.raises(ValueError, match="duration_minutes must be an integer"):
        cwd.build_log_workout_payload(db, "athlete-1", {"sport": "run", "duration_minutes": "abc"})
    with pytest.raises(ValueError, match="between 1 and 720"):
        cwd.build_log_workout_payload(db, "athlete-1", {"sport": "run", "duration_minutes": 0})


def test_build_log_workout_payload_rejects_avg_power_out_of_range():
    db = _athlete_db()
    with pytest.raises(ValueError, match="avg_power_w out of range"):
        cwd.build_log_workout_payload(
            db, "athlete-1", {"sport": "bike", "duration_minutes": 60, "avg_power_w": 5000}
        )


def test_build_log_workout_payload_defaults_norm_power_for_bike():
    db = _athlete_db()
    payload = cwd.build_log_workout_payload(
        db, "athlete-1", {"sport": "bike", "duration_minutes": 60, "avg_power_w": 200}
    )
    assert payload.normalized_power == 200


def test_build_log_workout_payload_default_title():
    db = _athlete_db()
    payload = cwd.build_log_workout_payload(db, "athlete-1", {"sport": "run", "duration_minutes": 45})
    assert "Run" in payload.title


# ---------------------------------------------------------------------------
# save_logged_workout / log_workout_sync
# ---------------------------------------------------------------------------


def test_save_logged_workout_delegates_to_canonical_and_process():
    db = MagicMock()
    payload = MagicMock(
        start_time=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
        workout_type="run",
        duration_seconds=1800,
        source="manual",
    )
    with patch.object(
        cwd, "find_or_create_canonical_workout", AsyncMock(return_value=({"id": "w1"}, True))
    ), patch.object(cwd, "process_and_save_workout", AsyncMock()) as mock_process:
        import asyncio

        workout_id, is_new = asyncio.run(cwd.save_logged_workout(db, "athlete-1", payload))

    assert workout_id == "w1"
    assert is_new is True
    mock_process.assert_awaited_once()


def test_log_workout_sync_returns_error_on_validation_failure():
    db = _athlete_db()
    result = cwd.log_workout_sync(db, "athlete-1", {})
    assert "error" in result


def test_log_workout_sync_returns_error_when_save_fails():
    db = _athlete_db()
    with patch.object(cwd, "save_logged_workout", AsyncMock(side_effect=RuntimeError("db down"))):
        result = cwd.log_workout_sync(db, "athlete-1", {"sport": "run", "duration_minutes": 30})
    assert "log_workout_failed" in result["error"]


def test_log_workout_sync_success_created():
    db = _athlete_db()
    saved_row = {"id": "w1", "sport": "run", "started_at": "2026-05-20T10:00:00Z", "duration_seconds": 1800, "tss": 40, "avg_power_w": None}
    with patch.object(cwd, "save_logged_workout", AsyncMock(return_value=("w1", True))), patch.object(
        cwd, "fetch_workout_by_id", return_value=saved_row
    ):
        result = cwd.log_workout_sync(db, "athlete-1", {"sport": "run", "duration_minutes": 30})

    assert result["status"] == "created"
    assert "Logged" in result["message"]


def test_log_workout_sync_success_merged():
    db = _athlete_db()
    saved_row = {"id": "w1", "sport": "run", "tss": 40}
    with patch.object(cwd, "save_logged_workout", AsyncMock(return_value=("w1", False))), patch.object(
        cwd, "fetch_workout_by_id", return_value=saved_row
    ):
        result = cwd.log_workout_sync(db, "athlete-1", {"sport": "run", "duration_minutes": 30})

    assert result["status"] == "merged"
    assert "Updated existing" in result["message"]


def test_log_workout_sync_error_when_saved_not_found():
    db = _athlete_db()
    with patch.object(cwd, "save_logged_workout", AsyncMock(return_value=("w1", True))), patch.object(
        cwd, "fetch_workout_by_id", return_value=None
    ):
        result = cwd.log_workout_sync(db, "athlete-1", {"sport": "run", "duration_minutes": 30})
    assert result["error"] == "workout_saved_but_not_found"


# ---------------------------------------------------------------------------
# list_workouts_compact
# ---------------------------------------------------------------------------


def test_list_workouts_compact_invalid_limit():
    db = _Db()
    assert cwd.list_workouts_compact(db, "athlete-1", {"limit": "abc"})["error"] == "limit must be an integer"


def test_list_workouts_compact_invalid_date():
    db = _Db()
    result = cwd.list_workouts_compact(db, "athlete-1", {"on_date": "not-a-date"})
    assert "invalid date" in result["error"]


def test_list_workouts_compact_success():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "workouts": SimpleNamespace(data=[{"id": "w1", "sport": "run"}]),
        }
    )
    result = cwd.list_workouts_compact(db, "athlete-1", {"start_date": "2026-05-01", "end_date": "2026-05-31", "sport": "run"})
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# _workout_patch_from_args / update_workout_sync
# ---------------------------------------------------------------------------


def test_workout_patch_from_args_title_and_scalar_fields():
    db = _athlete_db()
    existing = {"started_at": "2026-05-20T10:00:00Z", "duration_seconds": 1800}
    update = cwd._workout_patch_from_args(db, "athlete-1", existing, {"title": "  New title  ", "avg_hr": 150})
    assert update["title"] == "New title"
    assert update["avg_hr"] == 150


def test_workout_patch_from_args_blank_title_becomes_none():
    db = _athlete_db()
    update = cwd._workout_patch_from_args(db, "athlete-1", {}, {"title": "   "})
    assert update["title"] is None


def test_workout_patch_from_args_duration_minutes_updates_ended_at():
    db = _athlete_db()
    existing = {"started_at": "2026-05-20T10:00:00Z"}
    update = cwd._workout_patch_from_args(db, "athlete-1", existing, {"duration_minutes": 45})
    assert update["duration_seconds"] == 2700
    assert "ended_at" in update


def test_workout_patch_from_args_on_date_reschedules_using_existing_time():
    db = _athlete_db(offset_min=0)
    existing = {"started_at": "2026-05-20T10:00:00Z", "duration_seconds": 1800}
    update = cwd._workout_patch_from_args(db, "athlete-1", existing, {"on_date": "2026-05-25"})
    assert update["started_at"].startswith("2026-05-25T10:00:00")


def test_workout_patch_from_args_on_date_without_existing_start_uses_current_local_time():
    db = _athlete_db(offset_min=0)
    now = datetime(2026, 5, 20, 9, 15, tzinfo=timezone.utc)
    with patch.object(cwd, "athlete_local_datetime", return_value=now):
        update = cwd._workout_patch_from_args(db, "athlete-1", {}, {"on_date": "2026-05-25"})
    assert update["started_at"].startswith("2026-05-25T09:15:00")


def test_update_workout_sync_not_found():
    db = _Db()
    assert cwd.update_workout_sync(db, "athlete-1", {"workout_id": "w1"}) == {"error": "workout_not_found"}


def test_update_workout_sync_no_fields():
    db = _Db({"workouts": SimpleNamespace(data={"id": "w1"})})
    result = cwd.update_workout_sync(db, "athlete-1", {"workout_id": "w1"})
    assert result["error"] == "no_fields_to_update"


def test_update_workout_sync_success():
    db = _Db(
        {
            "workouts": SimpleNamespace(data={"id": "w1", "started_at": "2026-05-20T10:00:00Z"}),
        }
    )
    with patch.object(cwd, "recalculate_tss_history"), patch.object(cwd, "_refresh_daily_strain_for_day_sync"):
        result = cwd.update_workout_sync(db, "athlete-1", {"workout_id": "w1", "avg_hr": 150})
    assert result["status"] == "updated"


def test_update_workout_sync_error_on_db_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "w1", "started_at": "2026-05-20T10:00:00Z"}
    )
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    result = cwd.update_workout_sync(db, "athlete-1", {"workout_id": "w1", "avg_hr": 150})
    assert "update_workout_failed" in result["error"]


# ---------------------------------------------------------------------------
# log_biometrics_sync
# ---------------------------------------------------------------------------


def test_log_biometrics_sync_no_fields():
    db = _athlete_db()
    result = cwd.log_biometrics_sync(db, "athlete-1", {})
    assert result["error"] == "no_biometric_fields_provided"


def test_log_biometrics_sync_success():
    db = _athlete_db()
    with patch.object(cwd, "process_and_save_biometrics"):
        result = cwd.log_biometrics_sync(db, "athlete-1", {"resting_hr": 48, "hrv_rmssd": 55})
    assert result["status"] == "saved"


def test_log_biometrics_sync_with_sleep_times():
    db = _athlete_db()
    with patch.object(cwd, "process_and_save_biometrics"):
        result = cwd.log_biometrics_sync(
            db,
            "athlete-1",
            {
                "resting_hr": 48,
                "sleep_bedtime": "2026-05-19T22:00:00Z",
                "sleep_wakeup": "2026-05-20T06:00:00Z",
            },
        )
    assert "sleep_bedtime" in result["fields"]


def test_log_biometrics_sync_error_on_processing_failure():
    db = _athlete_db()
    with patch.object(cwd, "process_and_save_biometrics", side_effect=RuntimeError("boom")):
        result = cwd.log_biometrics_sync(db, "athlete-1", {"resting_hr": 48})
    assert "log_biometrics_failed" in result["error"]


# ---------------------------------------------------------------------------
# get_athlete_zones_payload
# ---------------------------------------------------------------------------


def test_get_athlete_zones_payload_error_on_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        RuntimeError("down")
    )
    result = cwd.get_athlete_zones_payload(db, "athlete-1")
    assert "athlete_query_failed" in result["error"]


def test_get_athlete_zones_payload_success():
    db = _Db({"athletes": SimpleNamespace(data={"max_hr": 190, "resting_hr": 50})})
    result = cwd.get_athlete_zones_payload(db, "athlete-1")
    assert "zones" in result
    assert len(result["zones"]) == 5


# ---------------------------------------------------------------------------
# resolve_plan_row / update_planned_workout_sync / delete_planned_workout_sync
# ---------------------------------------------------------------------------


def test_resolve_plan_row_by_id():
    db = _Db({"training_plans": SimpleNamespace(data={"id": "p1"})})
    assert cwd.resolve_plan_row(db, "athlete-1", {"plan_id": "p1"}) == {"id": "p1"}


def test_resolve_plan_row_returns_none_without_date():
    db = _Db()
    assert cwd.resolve_plan_row(db, "athlete-1", {}) is None


def test_resolve_plan_row_by_date_and_sport_filter():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "training_plans": SimpleNamespace(
                data=[{"id": "p1", "sport": "run"}, {"id": "p2", "sport": "bike"}]
            ),
        }
    )
    row = cwd.resolve_plan_row(db, "athlete-1", {"on_date": "2026-05-20", "sport": "bike"})
    assert row == {"id": "p2", "sport": "bike"}


def test_update_planned_workout_sync_not_found():
    db = _Db()
    assert cwd.update_planned_workout_sync(db, "athlete-1", {"plan_id": "p1"}) == {"error": "plan_not_found"}


def test_update_planned_workout_sync_no_fields():
    db = _Db({"training_plans": SimpleNamespace(data={"id": "p1"})})
    result = cwd.update_planned_workout_sync(db, "athlete-1", {"plan_id": "p1"})
    assert result["error"] == "no_fields_to_update"


def test_update_planned_workout_sync_success_with_structure():
    db = _Db({"training_plans": SimpleNamespace(data={"id": "p1"})})
    result = cwd.update_planned_workout_sync(
        db, "athlete-1", {"plan_id": "p1", "new_date": "2026-05-25", "structure": [{"a": 1}]}
    )
    assert result["status"] == "updated"


def test_update_planned_workout_sync_error_on_db_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "p1"}
    )
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    result = cwd.update_planned_workout_sync(db, "athlete-1", {"plan_id": "p1", "title": "New"})
    assert "update_plan_failed" in result["error"]


def test_delete_planned_workout_sync_not_found():
    db = _Db()
    assert cwd.delete_planned_workout_sync(db, "athlete-1", {"plan_id": "p1"}) == {"error": "plan_not_found"}


def test_delete_planned_workout_sync_success():
    db = _Db({"training_plans": SimpleNamespace(data={"id": "p1", "planned_date": "2026-05-20"})})
    result = cwd.delete_planned_workout_sync(db, "athlete-1", {"plan_id": "p1"})
    assert result["status"] == "deleted"


def test_delete_planned_workout_sync_error_on_db_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "p1", "planned_date": "2026-05-20"}
    )
    db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    result = cwd.delete_planned_workout_sync(db, "athlete-1", {"plan_id": "p1"})
    assert "delete_plan_failed" in result["error"]


# ---------------------------------------------------------------------------
# _resolve_date_range / _period_bounds
# ---------------------------------------------------------------------------


def test_resolve_date_range_defaults():
    db = _athlete_db()
    with patch.object(cwd, "athlete_local_date", return_value=date(2026, 5, 20)):
        start, end = cwd._resolve_date_range(db, "athlete-1", {}, default_days_back=7)
    assert end == date(2026, 5, 20)
    assert start == date(2026, 5, 13)


def test_resolve_date_range_raises_when_end_before_start():
    db = _athlete_db()
    with pytest.raises(ValueError):
        cwd._resolve_date_range(db, "athlete-1", {"start_date": "2026-05-20", "end_date": "2026-05-01"})


def test_period_bounds_week_and_month():
    db = _athlete_db()
    with patch.object(cwd, "athlete_local_date", return_value=date(2026, 5, 20)):
        week_start, week_end = cwd._period_bounds(db, "athlete-1", "week")
        month_start, month_end = cwd._period_bounds(db, "athlete-1", "month")
    assert week_end == date(2026, 5, 20)
    assert (week_end - week_start).days == 6
    assert (month_end - month_start).days == 29


def test_period_bounds_invalid_raises():
    db = _athlete_db()
    with pytest.raises(ValueError):
        cwd._period_bounds(db, "athlete-1", "year")


# ---------------------------------------------------------------------------
# list_planned_workouts_compact / get_training_load_series / get_biometrics_for_dates
# ---------------------------------------------------------------------------


def test_list_planned_workouts_compact_invalid_range():
    db = _athlete_db()
    result = cwd.list_planned_workouts_compact(db, "athlete-1", {"start_date": "2026-05-20", "end_date": "2026-05-01"})
    assert "error" in result


def test_list_planned_workouts_compact_success():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "training_plans": SimpleNamespace(data=[{"id": "p1", "planned_date": "2026-05-20"}]),
        }
    )
    result = cwd.list_planned_workouts_compact(db, "athlete-1", {})
    assert result["count"] == 1


def test_get_training_load_series_invalid_range():
    db = _athlete_db()
    result = cwd.get_training_load_series(db, "athlete-1", {"start_date": "2026-05-20", "end_date": "2026-05-01"})
    assert "error" in result


def test_get_training_load_series_query_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"timezone_offset_min": 0}
    )
    db.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.side_effect = RuntimeError(
        "down"
    )
    result = cwd.get_training_load_series(db, "athlete-1", {})
    assert "tss_history_query_failed" in result["error"]


def test_get_training_load_series_success():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "tss_history": SimpleNamespace(data=[{"date": "2026-05-20", "ctl": 50, "atl": 40, "tsb": 10, "daily_tss": 80}]),
        }
    )
    result = cwd.get_training_load_series(db, "athlete-1", {})
    assert result["count"] == 1


def test_get_biometrics_for_dates_requires_dates_array():
    db = _Db()
    assert cwd.get_biometrics_for_dates(db, "athlete-1", {})["error"] == "dates array is required"


def test_get_biometrics_for_dates_rejects_too_many():
    db = _Db()
    result = cwd.get_biometrics_for_dates(db, "athlete-1", {"dates": [f"2026-05-{i:02d}" for i in range(1, 10)]})
    assert "max" in result["error"]


def test_get_biometrics_for_dates_invalid_date():
    db = _Db()
    result = cwd.get_biometrics_for_dates(db, "athlete-1", {"dates": ["not-a-date"]})
    assert "invalid date" in result["error"]


def test_get_biometrics_for_dates_query_failure():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.execute.side_effect = (
        RuntimeError("down")
    )
    result = cwd.get_biometrics_for_dates(db, "athlete-1", {"dates": ["2026-05-20"]})
    assert "biometrics_query_failed" in result["error"]


def test_get_biometrics_for_dates_marks_missing_days():
    db = _Db({"biometrics": SimpleNamespace(data=[{"date": "2026-05-20", "hrv_rmssd": 55}])})
    result = cwd.get_biometrics_for_dates(db, "athlete-1", {"dates": ["2026-05-20", "2026-05-21"]})
    assert result["days"][0]["hrv_rmssd"] == 55
    assert result["days"][1] == {"date": "2026-05-21", "available": False}


# ---------------------------------------------------------------------------
# summarize_workouts / compare_workouts / _numeric_delta
# ---------------------------------------------------------------------------


def test_summarize_workouts_invalid_period():
    db = _athlete_db()
    result = cwd.summarize_workouts(db, "athlete-1", {"period": "year"})
    assert "error" in result


def test_summarize_workouts_aggregates_correctly():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "workouts": SimpleNamespace(
                data=[
                    {"sport": "run", "tss": 50, "duration_seconds": 1800},
                    {"sport": "bike", "tss": 80, "duration_seconds": 3600},
                ]
            ),
        }
    )
    with patch.object(cwd, "athlete_local_date", return_value=date(2026, 5, 20)):
        result = cwd.summarize_workouts(db, "athlete-1", {"period": "week"})
    assert result["workout_count"] == 2
    assert result["total_tss"] == 130.0
    assert result["hardest_session"]["tss"] == 80


def test_numeric_delta_handles_invalid_inputs():
    assert cwd._numeric_delta(None, 5) is None
    assert cwd._numeric_delta(5, None) is None
    assert cwd._numeric_delta("a", "b") is None
    assert cwd._numeric_delta(5, 8) == 3.0


def test_compare_workouts_requires_both_ids():
    db = _Db()
    result = cwd.compare_workouts(db, "athlete-1", {"workout_id_a": "w1"})
    assert "required" in result["error"]


# ---------------------------------------------------------------------------
# Remaining scattered branch gaps
# ---------------------------------------------------------------------------


def test_duration_secs_swallows_bad_int_cast():
    assert cwd._duration_secs({"duration_seconds": "not-a-number"}) is None


def test_duration_secs_normalizes_naive_started_at_when_ended_at_aware():
    row = {"started_at": "2026-05-20T10:00:00", "ended_at": "2026-05-20T11:00:00Z"}
    assert cwd._duration_secs(row) == 3600


def test_downsample_passthrough_when_shorter_than_target():
    assert cwd._downsample([1.0, 2.0, 3.0], 45) == [1.0, 2.0, 3.0]


def test_slice_stream_window_skips_metric_with_all_none_values():
    row = {"time_series": {"heartrate": [None, None, None], "watts": [100.0] * 10}, "resolution_seconds": 1}
    db = MagicMock()
    with patch.object(cwd, "fetch_stream_row_columns", return_value=row):
        result = cwd.slice_stream_window(
            db, "athlete-1", "w1", start_offset_min=0, end_offset_min=1, metrics=["hr", "power"]
        )
    assert "hr" not in result["metrics"]
    assert "power" in result["metrics"]


def test_build_log_workout_payload_accepts_explicit_norm_power():
    db = _athlete_db()
    payload = cwd.build_log_workout_payload(
        db, "athlete-1", {"sport": "bike", "duration_minutes": 60, "avg_power_w": 200, "norm_power_w": 215}
    )
    assert payload.normalized_power == 215


def test_build_log_workout_payload_uses_provided_title():
    db = _athlete_db()
    payload = cwd.build_log_workout_payload(
        db, "athlete-1", {"sport": "run", "duration_minutes": 30, "title": "Custom title"}
    )
    assert payload.title == "Custom title"


def test_save_logged_workout_normalizes_naive_start_time():
    db = MagicMock()
    payload = MagicMock(
        start_time=datetime(2026, 5, 20, 10, 0),  # naive
        workout_type="run",
        duration_seconds=1800,
        source="manual",
    )
    with patch.object(
        cwd, "find_or_create_canonical_workout", AsyncMock(return_value=({"id": "w1"}, True))
    ) as mock_find, patch.object(cwd, "process_and_save_workout", AsyncMock()):
        import asyncio

        asyncio.run(cwd.save_logged_workout(db, "athlete-1", payload))

    started_at_arg = mock_find.call_args[0][4]
    assert started_at_arg.tzinfo is not None


def test_update_workout_sync_normalizes_naive_existing_started_at():
    db = _Db(
        {
            "workouts": SimpleNamespace(data={"id": "w1", "started_at": "2026-05-20T10:00:00"}),
        }
    )
    with patch.object(cwd, "recalculate_tss_history"), patch.object(cwd, "_refresh_daily_strain_for_day_sync"):
        result = cwd.update_workout_sync(db, "athlete-1", {"workout_id": "w1", "on_date": "2026-05-25"})
    assert result["status"] == "updated"


def test_resolve_plan_row_returns_none_when_sport_filter_matches_nothing():
    db = _Db(
        {
            "athletes": SimpleNamespace(data={"timezone_offset_min": 0}),
            "training_plans": SimpleNamespace(data=[{"id": "p1", "sport": "run"}]),
        }
    )
    row = cwd.resolve_plan_row(db, "athlete-1", {"on_date": "2026-05-20", "sport": "swim"})
    assert row is None


def test_update_planned_workout_sync_updates_title_and_focus_zone():
    db = _Db({"training_plans": SimpleNamespace(data={"id": "p1"})})
    result = cwd.update_planned_workout_sync(
        db, "athlete-1", {"plan_id": "p1", "title": "New title", "focus_zone": "Threshold"}
    )
    assert result["status"] == "updated"
