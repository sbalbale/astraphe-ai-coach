from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import intervals_icu


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Config / request helpers
# ---------------------------------------------------------------------------


def test_api_base_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", None)
    with pytest.raises(HTTPException) as exc_info:
        intervals_icu._api_base()
    assert exc_info.value.status_code == 503


def test_api_base_strips_trailing_slash(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", "https://intervals.icu/api/v1/")
    assert intervals_icu._api_base() == "https://intervals.icu/api/v1"


def test_request_kwargs_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_AUTH_MODE", "basic")
    with pytest.raises(HTTPException) as exc_info:
        intervals_icu._request_kwargs("  ")
    assert exc_info.value.status_code == 400


def test_request_kwargs_basic_auth_mode(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_AUTH_MODE", "basic")
    kwargs = intervals_icu._request_kwargs("secret-key")
    assert "auth" in kwargs


def test_request_kwargs_api_key_header_mode(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_AUTH_MODE", intervals_icu.AUTH_MODE_API_KEY_HEADER)
    kwargs = intervals_icu._request_kwargs("secret-key")
    assert kwargs["headers"]["Authorization"] == "ApiKey secret-key"


def test_intervals_error_includes_body_snippet():
    resp = SimpleNamespace(status_code=500, text="server exploded")
    err = intervals_icu._intervals_error(resp, "test op")
    assert err.status_code == 500
    assert "server exploded" in err.detail


def test_intervals_error_handles_unreadable_body():
    class _BadResponse:
        status_code = 502

        @property
        def text(self):
            raise RuntimeError("no body")

    err = intervals_icu._intervals_error(_BadResponse(), "test op")
    assert "<unavailable>" in err.detail


# ---------------------------------------------------------------------------
# _get_json
# ---------------------------------------------------------------------------


class _FakeGetResponse:
    def __init__(self, status_code=200, json_data=None, json_error=False, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error
        self.text = text

    def json(self):
        if self._json_error:
            raise ValueError("bad json")
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, *_a, response=None, **_k):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, *_a, **_k):
        return self._response


def _patch_client(resp):
    return patch.object(intervals_icu.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(*a, response=resp, **k))


def test_get_json_raises_intervals_error_on_bad_status(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", "https://intervals.icu/api/v1")
    resp = _FakeGetResponse(status_code=404, text="not found")
    with _patch_client(resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(intervals_icu._get_json("path", "key", label="test"))
    assert exc_info.value.status_code == 404


def test_get_json_raises_502_on_non_json_success(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", "https://intervals.icu/api/v1")
    resp = _FakeGetResponse(status_code=200, json_error=True, text="<html>")
    with _patch_client(resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(intervals_icu._get_json("path", "key", label="test"))
    assert exc_info.value.status_code == 502


def test_get_json_returns_parsed_payload(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", "https://intervals.icu/api/v1")
    resp = _FakeGetResponse(status_code=200, json_data={"a": 1})
    with _patch_client(resp):
        result = _run_async(intervals_icu._get_json("path", "key", label="test"))
    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# Pure mapping helpers
# ---------------------------------------------------------------------------


def test_as_list_from_dict_container():
    payload = {"wellness": [{"a": 1}, "not-a-dict", {"b": 2}]}
    assert intervals_icu._as_list(payload, "wellness") == [{"a": 1}, {"b": 2}]


def test_as_list_returns_empty_for_unrecognized_shape():
    assert intervals_icu._as_list("not-a-list-or-dict", "key") == []
    assert intervals_icu._as_list({"other_key": [1]}, "wellness") == []


def test_float_returns_none_for_bool_and_unparseable():
    assert intervals_icu._float({"v": True}, "v") is None
    assert intervals_icu._float({"v": "abc"}, "v") is None
    assert intervals_icu._float({"v": "3.5"}, "v") == 3.5


def test_parse_datetime_handles_date_and_invalid_string():
    result = intervals_icu._parse_datetime(date(2026, 5, 20))
    assert result.tzinfo is not None
    assert intervals_icu._parse_datetime("not-a-date") is None
    assert intervals_icu._parse_datetime(None) is None


def test_parse_datetime_naive_string_gets_utc():
    result = intervals_icu._parse_datetime("2026-05-20T10:00:00")
    assert result.tzinfo == timezone.utc


def test_parse_date_from_datetime_and_fallback_string():
    assert intervals_icu._parse_date(datetime(2026, 5, 20, 10, 0)) == date(2026, 5, 20)
    assert intervals_icu._parse_date(date(2026, 5, 20)) == date(2026, 5, 20)
    assert intervals_icu._parse_date("2026-05-20T10:00:00Z") == date(2026, 5, 20)
    assert intervals_icu._parse_date("garbage-not-a-date") is None
    assert intervals_icu._parse_date(None) is None


def test_minutes_converts_seconds_hours_and_sleep_variants():
    assert intervals_icu._minutes({"sleepSecs": 3600}, "sleepSecs") == 60
    assert intervals_icu._minutes({"sleep_hours": 8}, "sleep_hours") == 480
    assert intervals_icu._minutes({"sleep": 5}, "sleep") == 300  # <=24 treated as hours
    assert intervals_icu._minutes({"sleep": 450}, "sleep") == 450  # already minutes
    assert intervals_icu._minutes({"v": None}, "v") is None


def test_percentage_prefers_direct_value_then_falls_back_to_minutes():
    entry = {"sleep_deep_pct": 25.0}
    assert intervals_icu._percentage(entry, ("sleep_deep_pct",), ("deepSecs",), 400) == 25.0

    entry2 = {"deepSecs": 3600}
    assert intervals_icu._percentage(entry2, ("sleep_deep_pct",), ("deepSecs",), 120) == 50.0

    assert intervals_icu._percentage({}, ("x",), ("y",), None) is None
    assert intervals_icu._percentage({}, ("x",), ("y",), 0) is None


def test_seconds_converts_minutes_to_seconds():
    assert intervals_icu._seconds({"duration_minutes": 30}, "duration_minutes") == 1800
    assert intervals_icu._seconds({"elapsed_time": 1800}, "elapsed_time") == 1800


def test_source_id_returns_none_for_missing_id():
    assert intervals_icu._source_id({}) is None
    assert intervals_icu._source_id({"id": 12345}) == "12345"


def test_map_wellness_falls_back_to_today_when_date_unparseable():
    entry = {"hrv": 55}
    bio = intervals_icu._map_wellness_to_daily_biometrics(entry)
    assert bio.date == datetime.now(timezone.utc).date()


def test_map_activity_to_workout_payload_none_without_start_time():
    assert intervals_icu._map_activity_to_workout_payload({}) is None


def test_map_activity_to_workout_payload_computes_ended_at_from_duration():
    activity = {
        "start_date": "2026-05-20T10:00:00Z",
        "elapsed_time": 3600,
        "type": "Run",
    }
    payload = intervals_icu._map_activity_to_workout_payload(activity)
    assert payload is not None
    assert payload.ended_at == payload.start_time.replace(hour=11)


# ---------------------------------------------------------------------------
# Stream normalization edge cases
# ---------------------------------------------------------------------------


def test_coerce_latlng_series_filters_out_of_range_points():
    value = {"data": [45.0, 999.0], "data2": [-73.0, -73.0]}
    points = intervals_icu._coerce_latlng_series(value)
    assert points == [[45.0, -73.0]]


def test_coerce_latlng_series_returns_none_for_mismatched_types():
    assert intervals_icu._coerce_latlng_series({"data": "not-a-list", "data2": []}) is None


def test_normalize_streams_payload_list_shape_skips_missing_series():
    payload = [
        {"type": "heartrate", "data": [140, 150]},
        {"type": "latlng", "data": [45.0], "data2": [-73.0]},
        {"type": "cadence"},  # no series
        "not-a-dict",
    ]
    out = intervals_icu._normalize_streams_payload(payload)
    assert out["heartrate"] == [140, 150]
    assert out["latlng"] == [[45.0, -73.0]]
    assert "cadence" not in out


def test_normalize_streams_payload_unwraps_nested_streams_key():
    payload = {"streams": {"heartrate": {"data": [1, 2]}}}
    out = intervals_icu._normalize_streams_payload(payload)
    assert out == {"heartrate": [1, 2]}


def test_normalize_streams_payload_returns_empty_for_unrecognized_shape():
    assert intervals_icu._normalize_streams_payload("not-a-dict-or-list") == {}
    assert intervals_icu._normalize_streams_payload(None) == {}


def test_fetch_activity_streams_returns_empty_for_blank_id():
    assert _run_async(intervals_icu.fetch_activity_streams("", "key")) == {}


# ---------------------------------------------------------------------------
# HR sample / zone helpers
# ---------------------------------------------------------------------------


def test_hr_samples_from_streams_filters_out_of_range_and_non_numeric():
    streams = {"heartrate": [140, None, True, "abc", 999, 55]}
    samples = intervals_icu._hr_samples_from_streams(streams)
    assert samples == [140, 55]


def test_hr_samples_from_streams_empty_when_not_a_list():
    assert intervals_icu._hr_samples_from_streams({"heartrate": "nope"}) == []


def test_hr_summary_columns_empty_without_samples():
    assert intervals_icu._hr_summary_columns_from_streams({}) == {}


def test_update_athlete_hr_anchors_skips_out_of_range_values():
    db = MagicMock()
    activity = {"athlete_max_hr": 500, "icu_resting_hr": 10, "lthr": 150}
    update = intervals_icu._update_athlete_hr_anchors_from_activity(db, "athlete-1", activity)
    assert update == {"threshold_hr": 150, "threshold_hr_source": "estimated"}
    db.table.assert_called_once_with("athletes")


def test_update_athlete_hr_anchors_noop_when_nothing_in_range():
    db = MagicMock()
    update = intervals_icu._update_athlete_hr_anchors_from_activity(db, "athlete-1", {})
    assert update == {}
    db.table.assert_not_called()


def test_upsert_activity_streams_noop_for_empty_series():
    db = MagicMock()
    assert intervals_icu._upsert_activity_streams(db, "w1", "athlete-1", {}) is False
    db.table.assert_not_called()


def test_upsert_activity_streams_inserts_when_no_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    with patch.object(intervals_icu.stream_storage, "upload_time_series_gzip", return_value=("path", 123)):
        result = intervals_icu._upsert_activity_streams(db, "w1", "athlete-1", {"heartrate": [1, 2]})
    assert result is True
    db.table.return_value.insert.assert_called_once()


def test_upsert_activity_streams_updates_when_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "row-1"}
    )
    with patch.object(intervals_icu.stream_storage, "upload_time_series_gzip", return_value=("path", 123)):
        result = intervals_icu._upsert_activity_streams(db, "w1", "athlete-1", {"heartrate": [1, 2]})
    assert result is True
    db.table.return_value.update.assert_called_once()


def test_hr_zone_columns_empty_without_hr_samples():
    db = MagicMock()
    assert intervals_icu._hr_zone_columns_from_streams(db, "athlete-1", {}) == {}
    db.table.assert_not_called()


def test_hr_zone_columns_computes_distribution_and_strain():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"max_hr": 190, "resting_hr": 50}
    )
    streams = {"heartrate": [150] * 120}  # 2 minutes of data
    out = intervals_icu._hr_zone_columns_from_streams(db, "athlete-1", streams)
    assert "avg_hr" in out
    assert "strain_score" in out


def test_update_workout_hr_zones_from_streams_noop_when_no_update():
    db = MagicMock()
    assert intervals_icu._update_workout_hr_zones_from_streams(db, "w1", "athlete-1", {}) is False
    db.table.assert_not_called()


def test_update_workout_hr_zones_from_streams_updates_workout():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"max_hr": 190, "resting_hr": 50}
    )
    streams = {"heartrate": [150] * 120}
    result = intervals_icu._update_workout_hr_zones_from_streams(db, "w1", "athlete-1", streams)
    assert result is True


# ---------------------------------------------------------------------------
# fetch_workouts / verify_credentials
# ---------------------------------------------------------------------------


def test_fetch_workouts_filters_unmappable_activities():
    async def _fake_summaries(*_a, **_k):
        return [{"start_date": "2026-05-20T10:00:00Z", "type": "Run"}, {"no": "start_date"}]

    with patch.object(intervals_icu, "fetch_activity_summaries", _fake_summaries):
        result = _run_async(
            intervals_icu.fetch_workouts("iid", "key", date(2026, 5, 1), date(2026, 5, 31))
        )
    assert len(result) == 1


def test_verify_credentials_calls_fetch_biometrics_for_today():
    calls = {}

    async def _fake_fetch_biometrics(intervals_athlete_id, api_key, start_date, end_date):
        calls["args"] = (intervals_athlete_id, api_key, start_date, end_date)
        return []

    with patch.object(intervals_icu, "fetch_biometrics", _fake_fetch_biometrics):
        _run_async(intervals_icu.verify_credentials("iid", "key"))

    assert calls["args"][0] == "iid"
    assert calls["args"][2] == calls["args"][3]  # start == end == today


# ---------------------------------------------------------------------------
# backfill_historical_data
# ---------------------------------------------------------------------------


def test_backfill_historical_data_aggregates_counts():
    activity = {"start_date": "2026-05-20T10:00:00Z", "type": "Run", "id": "a1"}
    bio_entry = {"date": "2026-05-20", "hrv": 55}

    async def _fake_summaries(*_a, **_k):
        return [activity]

    async def _fake_save(activity_, athlete_id, api_key, db):
        return True, True

    async def _fake_biometrics(*_a, **_k):
        return [intervals_icu._map_wellness_to_daily_biometrics(bio_entry)]

    async def _fake_recompute(*_a, **_k):
        return None

    with patch.object(intervals_icu, "fetch_activity_summaries", _fake_summaries), patch.object(
        intervals_icu, "_save_activity_summary_and_streams", _fake_save
    ), patch.object(intervals_icu, "fetch_biometrics", _fake_biometrics), patch.object(
        intervals_icu, "recompute_workout_tss_for_athlete", _fake_recompute
    ), patch.object(intervals_icu, "recalculate_tss_history", MagicMock()), patch.object(
        intervals_icu, "process_and_save_biometrics", MagicMock()
    ), patch.object(intervals_icu, "invalidate_context_cache", MagicMock()):
        result = _run_async(
            intervals_icu.backfill_historical_data("athlete-1", "iid", "key", MagicMock(), days=30)
        )

    assert result == {"workouts": 1, "streams": 1, "biometrics": 1, "days": 30}


def test_backfill_historical_data_clamps_days_range():
    async def _fake_summaries(*_a, **_k):
        return []

    async def _fake_biometrics(*_a, **_k):
        return []

    async def _fake_recompute(*_a, **_k):
        return None

    with patch.object(intervals_icu, "fetch_activity_summaries", _fake_summaries), patch.object(
        intervals_icu, "fetch_biometrics", _fake_biometrics
    ), patch.object(intervals_icu, "recompute_workout_tss_for_athlete", _fake_recompute), patch.object(
        intervals_icu, "recalculate_tss_history", MagicMock()
    ), patch.object(intervals_icu, "invalidate_context_cache", MagicMock()):
        result = _run_async(
            intervals_icu.backfill_historical_data("athlete-1", "iid", "key", MagicMock(), days=9999)
        )

    assert result["days"] == 365


def test_parse_datetime_from_date_object():
    result = intervals_icu._parse_datetime(date(2026, 5, 20))
    assert result == datetime(2026, 5, 20, tzinfo=timezone.utc)


def test_minutes_converts_oversized_sleep_value_from_seconds():
    # A "sleep" key with a value > 24*60 is assumed to actually be seconds, not minutes.
    assert intervals_icu._minutes({"sleep": 30000}, "sleep") == 500


def test_fetch_activity_streams_reraises_non_unavailable_http_errors(monkeypatch):
    monkeypatch.setattr(settings, "INTERVALS_ICU_API_BASE", "https://intervals.icu/api/v1")
    resp = _FakeGetResponse(status_code=500, text="server error")
    with _patch_client(resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(intervals_icu.fetch_activity_streams("act-1", "key"))
    assert exc_info.value.status_code == 500


def test_save_activity_summary_and_streams_returns_false_for_unmappable_activity():
    result = _run_async(
        intervals_icu._save_activity_summary_and_streams({}, "athlete-1", "key", MagicMock())
    )
    assert result == (False, False)


def test_save_activity_summary_and_streams_success_with_streams():
    activity = {"start_date": "2026-05-20T10:00:00Z", "type": "Run", "id": "a1"}
    db = MagicMock()

    with patch.object(
        intervals_icu, "_update_athlete_hr_anchors_from_activity", MagicMock()
    ) as mock_anchors, patch.object(
        intervals_icu, "process_and_save_workout", AsyncMock(return_value="w1")
    ), patch.object(
        intervals_icu, "fetch_activity_streams", AsyncMock(return_value={"heartrate": [1, 2]})
    ), patch.object(
        intervals_icu, "_upsert_activity_streams", return_value=True
    ), patch.object(
        intervals_icu, "_update_workout_hr_zones_from_streams", MagicMock()
    ) as mock_hr_zones:
        saved_workout, saved_streams = _run_async(
            intervals_icu._save_activity_summary_and_streams(activity, "athlete-1", "key", db)
        )

    assert saved_workout is True
    assert saved_streams is True
    mock_anchors.assert_called_once()
    mock_hr_zones.assert_called_once()


def test_save_activity_summary_and_streams_logs_when_streams_unavailable():
    activity = {"start_date": "2026-05-20T10:00:00Z", "type": "Run", "id": "a1"}
    db = MagicMock()

    with patch.object(intervals_icu, "_update_athlete_hr_anchors_from_activity", MagicMock()), patch.object(
        intervals_icu, "process_and_save_workout", AsyncMock(return_value="w1")
    ), patch.object(
        intervals_icu, "fetch_activity_streams", AsyncMock(return_value={})
    ), patch.object(intervals_icu, "_upsert_activity_streams", return_value=False):
        saved_workout, saved_streams = _run_async(
            intervals_icu._save_activity_summary_and_streams(activity, "athlete-1", "key", db)
        )

    assert saved_workout is True
    assert saved_streams is False
