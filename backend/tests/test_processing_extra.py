from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import processing


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Sport normalization
# ---------------------------------------------------------------------------


def test_normalize_sport_blank_returns_other():
    assert processing.normalize_sport("") == "other"
    assert processing.normalize_sport(None) == "other"


def test_normalize_sport_maps_known_vendor_strings():
    assert processing.normalize_sport("Ride") == "bike"
    assert processing.normalize_sport("  TRAILRUN ") == "run"


def test_sport_for_db_passes_through_db_enum():
    assert processing._sport_for_db("run") == "run"


def test_sport_for_db_maps_legacy_and_unknown():
    assert processing._sport_for_db("cycling") == "bike"
    assert processing._sport_for_db("something-weird") == "other"


# ---------------------------------------------------------------------------
# Strava source id merging
# ---------------------------------------------------------------------------


def test_merge_strava_source_ids_creates_list_when_absent():
    d: dict = {}
    processing._merge_strava_source_ids(d, 123)
    assert d["strava"] == ["123"]


def test_merge_strava_source_ids_appends_to_existing_string():
    d = {"strava": "111"}
    processing._merge_strava_source_ids(d, 222)
    assert d["strava"] == ["111", "222"]


def test_merge_strava_source_ids_appends_to_existing_list_without_dupes():
    d = {"strava": ["111", "222"]}
    processing._merge_strava_source_ids(d, 222)
    assert d["strava"] == ["111", "222"]


def test_merge_strava_source_ids_replaces_unexpected_type():
    d = {"strava": 42}
    processing._merge_strava_source_ids(d, 111)
    assert d["strava"] == ["111"]


def test_strip_none_update_values_keeps_falsy_non_none():
    assert processing._strip_none_update_values({"a": None, "b": 0, "c": "", "d": "x"}) == {
        "b": 0,
        "c": "",
        "d": "x",
    }


# ---------------------------------------------------------------------------
# Quality merge helpers
# ---------------------------------------------------------------------------


def test_source_quality_rank_unknown_field_uses_default_order():
    rank_strava = processing._source_quality_rank("unmapped_field", "strava")
    rank_manual = processing._source_quality_rank("unmapped_field", "manual")
    assert rank_strava < rank_manual


def test_source_quality_rank_unknown_source_ranks_last():
    assert processing._source_quality_rank("title", "unknown_vendor") == len(
        processing._QUALITY_FIELD_SOURCES["title"]
    )


def test_has_existing_metric_value():
    assert processing._has_existing_metric_value(None) is False
    assert processing._has_existing_metric_value("") is False
    assert processing._has_existing_metric_value(0) is True
    assert processing._has_existing_metric_value("x") is True


def test_quality_filter_passes_through_unmapped_fields():
    existing = {"source": "strava", "primary_source": "strava"}
    filtered = processing._quality_filter_workout_update(
        existing, "manual", {"some_custom_field": "value", "title": None}
    )
    assert filtered == {"some_custom_field": "value"}


def test_biometric_source_quality_rank_defaults_to_manual_only():
    assert processing._biometric_source_quality_rank("unmapped_field", "whoop") == 1  # not in ("manual",)
    assert processing._biometric_source_quality_rank("unmapped_field", "manual") == 0


def test_choose_biometric_metric_prefers_existing_when_incoming_missing():
    existing = {"hrv_rmssd": 55.0}
    value, source = processing._choose_biometric_metric(existing, {"hrv_rmssd": "whoop"}, "hrv_rmssd", None, "garmin")
    assert value == 55.0
    assert source == "whoop"


def test_choose_biometric_metric_uses_incoming_when_no_existing_value():
    value, source = processing._choose_biometric_metric({}, {}, "hrv_rmssd", 60.0, "whoop")
    assert value == 60.0
    assert source == "whoop"


def test_choose_biometric_metric_higher_quality_incoming_wins():
    existing = {"resting_hr": 50}
    value, source = processing._choose_biometric_metric(
        existing, {"resting_hr": "manual"}, "resting_hr", 48, "whoop"
    )
    assert value == 48
    assert source == "whoop"


def test_choose_biometric_metric_lower_quality_incoming_loses():
    existing = {"resting_hr": 50}
    value, source = processing._choose_biometric_metric(
        existing, {"resting_hr": "whoop"}, "resting_hr", 48, "manual"
    )
    assert value == 50
    assert source == "whoop"


def test_set_metric_source_pops_when_no_value_or_source():
    sources = {"hrv_rmssd": "whoop"}
    processing._set_metric_source(sources, "hrv_rmssd", None, None)
    assert "hrv_rmssd" not in sources

    sources2 = {"hrv_rmssd": "whoop"}
    processing._set_metric_source(sources2, "hrv_rmssd", "garmin", 55.0)
    assert sources2["hrv_rmssd"] == "garmin"


def test_upsert_biometrics_sync_retries_without_metric_sources_on_schema_error():
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.side_effect = [
        RuntimeError("column metric_sources does not exist"),
        None,
    ]
    processing._upsert_biometrics_sync(db, {"athlete_id": "a1", "date": "2026-05-20", "metric_sources": {}})
    assert db.table.return_value.upsert.call_count == 2
    second_call_payload = db.table.return_value.upsert.call_args_list[1][0][0]
    assert "metric_sources" not in second_call_payload


def test_upsert_biometrics_sync_reraises_unrelated_errors():
    db = MagicMock()
    db.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("connection refused")
    try:
        processing._upsert_biometrics_sync(db, {"athlete_id": "a1", "date": "2026-05-20"})
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as e:
        assert "connection refused" in str(e)


# ---------------------------------------------------------------------------
# Workout duration / strain helpers
# ---------------------------------------------------------------------------


def test_parse_workout_dt_handles_various_inputs():
    assert processing._parse_workout_dt(None) is None
    dt = datetime(2026, 5, 20, 10, 0)
    assert processing._parse_workout_dt(dt) is dt
    assert processing._parse_workout_dt("2026-05-20T10:00:00Z") is not None
    assert processing._parse_workout_dt("not-a-date") is None
    assert processing._parse_workout_dt(12345) is None


def test_workout_duration_seconds_from_row_prefers_explicit_field():
    assert processing._workout_duration_seconds_from_row({"duration_seconds": 1800}) == 1800
    assert processing._workout_duration_seconds_from_row({"duration_secs": 900}) == 900


def test_workout_duration_seconds_from_row_falls_back_to_delta():
    row = {"started_at": "2026-05-20T10:00:00Z", "ended_at": "2026-05-20T11:00:00Z"}
    assert processing._workout_duration_seconds_from_row(row) == 3600


def test_workout_duration_seconds_from_row_zero_when_unparseable():
    assert processing._workout_duration_seconds_from_row({}) == 0


def test_compute_daily_strain_from_workout_rows_skips_zero_duration():
    rows = [{"duration_seconds": 0}, {"duration_seconds": 1800, "hr_zone_2_pct": 100}]
    strain = processing._compute_daily_strain_from_workout_rows(rows)
    assert strain > 0


def test_compute_sleep_score_without_architecture_zero_for_invalid_input():
    assert processing._compute_sleep_score_without_architecture(0, 480) == 0
    assert processing._compute_sleep_score_without_architecture(400, 0) == 0


def test_compute_sleep_score_without_architecture_low_ratio_branch():
    score = processing._compute_sleep_score_without_architecture(100, 480)  # ratio ~0.21
    assert 0 <= score <= 45


def test_compute_sleep_score_without_architecture_mid_ratio_branch():
    score = processing._compute_sleep_score_without_architecture(300, 480)  # ratio 0.625
    assert 45 <= score <= 70


def test_compute_sleep_score_without_architecture_high_ratio_branch():
    score = processing._compute_sleep_score_without_architecture(480, 480)  # ratio 1.0
    assert score >= 70


class _StrainQuery:
    def __init__(self, rows):
        self._rows = rows
        self.updated_payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
        return self

    def update(self, payload):
        self.updated_payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _StrainDb:
    def __init__(self, rows):
        self.workouts_query = _StrainQuery(rows)
        self.bio_query = _StrainQuery(rows)

    def table(self, name):
        if name == "workouts":
            return self.workouts_query
        if name == "biometrics":
            return self.bio_query
        raise AssertionError(name)


def test_refresh_daily_strain_for_day_sync_updates_biometrics():
    rows = [{"duration_seconds": 1800, "hr_zone_2_pct": 100, "started_at": "2026-05-20T08:00:00Z"}]
    db = _StrainDb(rows)
    strain = processing._refresh_daily_strain_for_day_sync(db, "athlete-1", date(2026, 5, 20))
    assert strain > 0
    assert db.bio_query.updated_payload == {"strain_score": strain}


def test_workout_dates_for_athlete_dedupes_and_sorts():
    rows = [
        {"started_at": "2026-05-20T10:00:00Z"},
        {"started_at": "2026-05-20T18:00:00Z"},
        {"started_at": "2026-05-19T10:00:00Z"},
        {"started_at": None},
    ]
    dates = processing._workout_dates_for_athlete(rows)
    assert dates == [date(2026, 5, 19), date(2026, 5, 20)]


def test_refresh_all_daily_strain_sync_iterates_all_workout_days():
    rows = [{"started_at": "2026-05-20T10:00:00Z", "duration_seconds": 1800, "hr_zone_1_pct": 100}]
    db = _StrainDb(rows)
    result = processing.refresh_all_daily_strain_sync(db, "athlete-1")
    assert result == {"days": 1}


# ---------------------------------------------------------------------------
# Athlete fetch / workout update helpers
# ---------------------------------------------------------------------------


def test_fetch_athlete_for_workout_sync_returns_empty_when_no_data():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert processing._fetch_athlete_for_workout_sync(db, "athlete-1") == {}


def test_fetch_athlete_for_workout_sync_returns_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
        data={"max_hr": 190}
    )
    assert processing._fetch_athlete_for_workout_sync(db, "athlete-1") == {"max_hr": 190}


def test_workouts_update_by_id_sync_noop_when_payload_empty_after_strip():
    db = MagicMock()
    processing._workouts_update_by_id_sync(db, "w1", {"a": None})
    db.table.assert_not_called()


def test_workouts_update_by_id_sync_updates_when_payload_present():
    db = MagicMock()
    processing._workouts_update_by_id_sync(db, "w1", {"title": "New title", "a": None})
    db.table.return_value.update.assert_called_once_with({"title": "New title"})


# ---------------------------------------------------------------------------
# Pace parsing
# ---------------------------------------------------------------------------


def test_parse_pace_to_sec_per_km_handles_various_formats():
    assert processing._parse_pace_to_sec_per_km(None) == 0.0
    assert processing._parse_pace_to_sec_per_km(300) == 300.0
    assert processing._parse_pace_to_sec_per_km(-5) == 0.0
    assert processing._parse_pace_to_sec_per_km("5:00") == 300.0
    assert processing._parse_pace_to_sec_per_km("5:00/km") == 300.0
    assert processing._parse_pace_to_sec_per_km("") == 0.0
    assert processing._parse_pace_to_sec_per_km("garbage") == 0.0
    assert processing._parse_pace_to_sec_per_km("1:2:3") == 0.0  # too many parts
    assert processing._parse_pace_to_sec_per_km("330") == 330.0


# ---------------------------------------------------------------------------
# recalculate_tss_history
# ---------------------------------------------------------------------------


class _TssQuery:
    def __init__(self, workout_rows, athlete_row=None):
        self._workout_rows = workout_rows
        self._athlete_row = athlete_row or {"timezone_offset_min": 0}
        self.deleted = None
        self.upserted = None
        self._table = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def single(self):
        return self

    def lt(self, *_a, **_k):
        return self

    def delete(self):
        self.deleted = True
        return self

    def upsert(self, records, **_k):
        self.upserted = records
        return self

    def execute(self):
        if self._table == "athletes":
            return SimpleNamespace(data=self._athlete_row)
        if self.upserted is not None or self.deleted:
            return SimpleNamespace(data=None)
        return SimpleNamespace(data=self._workout_rows)


class _TssDb:
    def __init__(self, workout_rows, athlete_row=None):
        self.query = _TssQuery(workout_rows, athlete_row)

    def table(self, name):
        self.query._table = name
        return self.query


def test_recalculate_tss_history_noop_without_workouts():
    db = _TssDb(workout_rows=[])
    processing.recalculate_tss_history("athlete-1", db)
    assert db.query.upserted is None


def test_recalculate_tss_history_upserts_pmc_records():
    rows = [{"started_at": "2026-05-20T10:00:00Z", "tss": 80.0}]
    db = _TssDb(rows)
    processing.recalculate_tss_history("athlete-1", db)
    assert db.query.upserted is not None
    assert db.query.upserted[0]["athlete_id"] == "athlete-1"
    assert db.query.deleted is True


# ---------------------------------------------------------------------------
# _workout_row_to_payload / recompute / reprocess
# ---------------------------------------------------------------------------


def test_workout_row_to_payload_builds_payload_from_row():
    row = {
        "source": "strava",
        "sport": "run",
        "started_at": "2026-05-20T10:00:00Z",
        "duration_seconds": 1800,
        "avg_hr": 150,
    }
    payload = processing._workout_row_to_payload(row)
    assert payload.workout_type == "run"
    assert payload.average_hr == 150
    assert payload.tss is None


def test_recompute_workout_tss_for_athlete_skips_rows_with_existing_tss():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = SimpleNamespace(
        data=[
            {"started_at": "2026-05-20T10:00:00Z", "tss": 50.0},
            {"started_at": "2026-05-21T10:00:00Z", "tss": None, "sport": "run"},
        ]
    )
    with patch.object(processing, "process_and_save_workout", AsyncMock(return_value="w2")) as mock_save:
        updated = _run_async(processing.recompute_workout_tss_for_athlete("athlete-1", db))

    assert updated == 1
    mock_save.assert_awaited_once()


def test_reprocess_athlete_metrics_rebuilds_workouts_and_biometrics():
    db = MagicMock()

    def _select_side_effect(*_a, **_k):
        return db.table.return_value

    db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = [
        SimpleNamespace(data=[{"started_at": "2026-05-20T10:00:00Z", "sport": "run"}]),
        SimpleNamespace(data=[{"date": "2026-05-20", "hrv_rmssd": 55.0}]),
    ]

    with patch.object(processing, "process_and_save_workout", AsyncMock()) as mock_save_workout, patch.object(
        processing, "process_and_save_biometrics", MagicMock()
    ) as mock_save_bio, patch.object(processing, "recalculate_tss_history", MagicMock()) as mock_recalc:
        result = _run_async(processing.reprocess_athlete_metrics("athlete-1", db))

    assert result == {"workouts": 1, "biometrics": 1}
    mock_save_workout.assert_awaited_once()
    mock_save_bio.assert_called_once()
    mock_recalc.assert_called_once_with("athlete-1", db)


# ---------------------------------------------------------------------------
# find_or_create_canonical_workout async wrapper
# ---------------------------------------------------------------------------


def test_find_or_create_canonical_workout_delegates_to_sync_impl():
    with patch.object(
        processing, "_find_or_create_canonical_workout_sync", return_value=({"id": "w1"}, True)
    ) as mock_sync:
        result = _run_async(
            processing.find_or_create_canonical_workout(
                MagicMock(), "athlete-1", "strava", "run", datetime.now(timezone.utc), 1800
            )
        )

    assert result == ({"id": "w1"}, True)
    mock_sync.assert_called_once()
