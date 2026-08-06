from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import strava


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_retry_after_seconds_uses_header_when_valid():
    resp = SimpleNamespace(headers={"Retry-After": "120"})
    assert strava._retry_after_seconds(resp) == 120


def test_retry_after_seconds_falls_back_when_missing_or_invalid():
    assert strava._retry_after_seconds(SimpleNamespace(headers={})) == strava.STRAVA_RATE_LIMIT_COOLDOWN_S
    assert strava._retry_after_seconds(SimpleNamespace(headers={"Retry-After": "not-a-number"})) == (
        strava.STRAVA_RATE_LIMIT_COOLDOWN_S
    )
    assert strava._retry_after_seconds(SimpleNamespace(headers={"Retry-After": "99999"})) == (
        strava.STRAVA_RATE_LIMIT_COOLDOWN_S
    )


def test_parse_strava_start_date_handles_invalid_and_valid():
    assert strava._parse_strava_start_date(None) is None
    assert strava._parse_strava_start_date(123) is None
    assert strava._parse_strava_start_date("not-a-date") is None
    assert strava._parse_strava_start_date("2026-05-20T10:00:00Z") is not None


def test_optional_smallint_clamps_and_handles_invalid():
    assert strava._optional_smallint(None) is None
    assert strava._optional_smallint("abc") is None
    assert strava._optional_smallint(-5) == 0
    assert strava._optional_smallint(99999) == 32767
    assert strava._optional_smallint(150.6) == 151


def test_avg_pace_sec_km_from_strava_handles_missing_and_zero_speed():
    assert strava._avg_pace_sec_km_from_strava({}) is None
    assert strava._avg_pace_sec_km_from_strava({"average_speed": 0}) is None
    assert strava._avg_pace_sec_km_from_strava({"average_speed": 4.0}) == 250


def test_hr_stream_zone_dist_to_workout_columns_maps_and_skips_unknown():
    zone_dist = {"Z1": 20.0, "Z2": 40.0, "unexpected": 5}
    cols = strava._hr_stream_zone_dist_to_workout_columns(zone_dist)
    assert cols["hr_zone_1_pct"] == 20
    assert cols["hr_zone_2_pct"] == 40
    assert "unexpected" not in cols


def test_hr_stream_zone_dist_to_workout_columns_empty_input():
    assert strava._hr_stream_zone_dist_to_workout_columns({}) == {}


def test_expires_ts_from_db_handles_all_input_shapes():
    assert strava._expires_ts_from_db(None) is None
    assert strava._expires_ts_from_db(1716200000.0) == 1716200000.0
    naive = datetime(2026, 5, 20, 10, 0)
    assert strava._expires_ts_from_db(naive) is not None
    assert strava._expires_ts_from_db("2026-05-20T10:00:00Z") is not None
    assert strava._expires_ts_from_db("not-a-date") is None
    assert strava._expires_ts_from_db(object()) is None


def test_expires_at_iso_from_strava_handles_missing_and_invalid():
    assert strava._expires_at_iso_from_strava({}) is None
    assert strava._expires_at_iso_from_strava({"expires_at": "not-a-number"}) is None
    result = strava._expires_at_iso_from_strava({"expires_at": 1716200000})
    assert result is not None and result.endswith("+00:00")


def test_strava_oauth_expires_at_iso_delegates():
    assert strava.strava_oauth_expires_at_iso({"expires_at": 1716200000}) == strava._expires_at_iso_from_strava(
        {"expires_at": 1716200000}
    )


def test_auth_headers_format():
    assert strava._auth_headers("tok123") == {"Authorization": "Bearer tok123"}


def test_time_series_to_streams_dict_delegates_to_stream_storage():
    result = strava._time_series_to_streams_dict({"heartrate": [1, 2]})
    assert result == {"heartrate": {"data": [1, 2]}}


def test_parse_raw_strava_payload_handles_all_shapes():
    assert strava._parse_raw_strava_payload(None) is None
    assert strava._parse_raw_strava_payload({"a": 1}) == {"a": 1}
    assert strava._parse_raw_strava_payload('{"a": 1}') == {"a": 1}
    assert strava._parse_raw_strava_payload("  ") is None
    assert strava._parse_raw_strava_payload("not-json") is None
    assert strava._parse_raw_strava_payload("[1,2,3]") is None  # valid json, not a dict
    assert strava._parse_raw_strava_payload(42) is None


def test_supabase_resp_data_handles_none_response():
    assert strava._supabase_resp_data(None) is None
    assert strava._supabase_resp_data(SimpleNamespace(data=[1, 2])) == [1, 2]


def test_supabase_single_row_normalizes_shapes():
    assert strava._supabase_single_row(None) is None
    assert strava._supabase_single_row(SimpleNamespace(data=None)) is None
    assert strava._supabase_single_row(SimpleNamespace(data={"a": 1})) == {"a": 1}
    assert strava._supabase_single_row(SimpleNamespace(data=[{"a": 1}])) == {"a": 1}
    assert strava._supabase_single_row(SimpleNamespace(data=[{"a": 1}, {"b": 2}])) is None
    assert strava._supabase_single_row(SimpleNamespace(data=[])) is None


def test_pick_best_laps_prefers_api_when_no_embedded():
    api = [{"distance": 500}]
    assert strava._pick_best_laps(api, None) == api


def test_pick_best_laps_prefers_embedded_when_no_api():
    emb = [{"distance": 500}]
    assert strava._pick_best_laps(None, emb) == emb


def test_pick_best_laps_prefers_more_laps():
    api = [{"distance": 500}]
    emb = [{"distance": 500}, {"distance": 500}]
    assert strava._pick_best_laps(api, emb) == emb


def test_pick_best_laps_prefers_embedded_when_single_synthetic_api_lap():
    api = [{"distance": 0}]  # synthetic single lap
    emb = [{"distance": 500}, {"distance": 500}]
    assert strava._pick_best_laps(api, emb) == emb


def test_pick_best_laps_equal_length_keeps_api():
    api = [{"distance": 5000}]
    emb = [{"distance": 2500}]
    assert strava._pick_best_laps(api, emb) == api


def test_stream_data_len_handles_missing_and_present():
    assert strava._stream_data_len(None, "heartrate") == 0
    assert strava._stream_data_len({}, "heartrate") == 0
    assert strava._stream_data_len({"heartrate": "not-a-dict"}, "heartrate") == 0
    assert strava._stream_data_len({"heartrate": {"data": [1, 2, 3]}}, "heartrate") == 3


def test_has_quality_value_various_types():
    assert strava._has_quality_value(None) is False
    assert strava._has_quality_value(True) is True
    assert strava._has_quality_value(False) is False
    assert strava._has_quality_value(0) is False
    assert strava._has_quality_value(5) is True
    assert strava._has_quality_value([]) is False
    assert strava._has_quality_value([1]) is True
    assert strava._has_quality_value("x") is True
    assert strava._has_quality_value({"nested": "dict"}) is True


def test_strava_detail_quality_score_increases_with_streams_and_laps():
    base = strava._strava_detail_quality_score(None, None, None)
    with_streams = strava._strava_detail_quality_score(
        None, {"heartrate": {"data": [1] * 100}}, None
    )
    with_laps = strava._strava_detail_quality_score(
        None, None, [{"distance": 500, "average_heartrate": 150}]
    )
    assert with_streams > base
    assert with_laps > base


def test_strava_id_string_handles_invalid():
    assert strava._strava_id_string(None) is None
    assert strava._strava_id_string("not-a-number") is None
    assert strava._strava_id_string(123) == "123"
    assert strava._strava_id_string("123") == "123"


def test_strava_activity_is_primary():
    workout = {"strava_activity_id": 111}
    assert strava._strava_activity_is_primary(workout, 111) is True
    assert strava._strava_activity_is_primary(workout, 222) is False
    assert strava._strava_activity_is_primary({}, 111) is False


def test_strava_activity_is_linked_via_source_ids_list():
    workout = {"strava_activity_id": 999, "source_ids": {"strava": ["111", "222"]}}
    assert strava._strava_activity_is_linked(workout, 111) is True
    assert strava._strava_activity_is_linked(workout, 333) is False


def test_strava_activity_is_linked_via_source_ids_string():
    workout = {"strava_activity_id": 999, "source_ids": {"strava": "111"}}
    assert strava._strava_activity_is_linked(workout, 111) is True


def test_strava_activity_is_linked_primary_short_circuits():
    workout = {"strava_activity_id": 111, "source_ids": {}}
    assert strava._strava_activity_is_linked(workout, 111) is True


# ---------------------------------------------------------------------------
# OAuth / HTTP client functions
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", json_error=False, headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._json_error = json_error
        self.headers = headers or {}

    def json(self):
        if self._json_error:
            raise ValueError("bad json")
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, *_a, get=None, post=None, **_k):
        self._get_response = get
        self._post_response = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, *_a, **_k):
        resp = self._get_response
        return resp(*_a, **_k) if callable(resp) else resp

    async def post(self, *_a, **_k):
        resp = self._post_response
        return resp(*_a, **_k) if callable(resp) else resp


def _patch_client(**kwargs):
    return patch.object(strava.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(*a, **kwargs, **k))


def test_exchange_oauth_code_success():
    resp = _FakeResponse(status_code=200, json_data={"access_token": "tok"})
    with _patch_client(post=resp):
        result = _run_async(strava.exchange_oauth_code("code-1", "https://redirect"))
    assert result == {"access_token": "tok"}


def test_exchange_oauth_code_raises_on_failure():
    resp = _FakeResponse(status_code=400, text="bad code")
    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava.exchange_oauth_code("bad", "https://redirect"))
    assert exc_info.value.status_code == 400


def test_refresh_oauth_token_success():
    resp = _FakeResponse(status_code=200, json_data={"access_token": "new-tok"})
    with _patch_client(post=resp):
        result = _run_async(strava.refresh_oauth_token("refresh-1"))
    assert result == {"access_token": "new-tok"}


def test_refresh_oauth_token_raises_on_failure():
    resp = _FakeResponse(status_code=401, text="invalid_grant")
    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava.refresh_oauth_token("bad-refresh"))
    assert exc_info.value.status_code == 401


def test_refresh_oauth_token_raises_502_on_non_json():
    resp = _FakeResponse(status_code=200, text="<html>", json_error=True)
    with _patch_client(post=resp):
        with pytest.raises(HTTPException) as exc_info:
            _run_async(strava.refresh_oauth_token("refresh-1"))
    assert exc_info.value.status_code == 502


def test_get_valid_token_returns_none_without_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert _run_async(strava.get_valid_token("athlete-1", db)) is None


def test_get_valid_token_returns_cached_when_not_expiring_soon():
    db = MagicMock()
    future_expiry = datetime.now(timezone.utc).timestamp() + 3600
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "cached-tok", "refresh_token": "r1", "expires_at": future_expiry}
    )
    assert _run_async(strava.get_valid_token("athlete-1", db)) == "cached-tok"


def test_get_valid_token_returns_none_without_refresh_token_when_expiring():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "old-tok", "refresh_token": None, "expires_at": 1.0}
    )
    assert _run_async(strava.get_valid_token("athlete-1", db)) is None


def test_get_valid_token_refreshes_and_persists_when_expiring():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "old-tok", "refresh_token": "r1", "expires_at": 1.0}
    )
    with patch.object(
        strava,
        "refresh_oauth_token",
        AsyncMock(return_value={"access_token": "new-tok", "refresh_token": "r2", "expires_at": 1716200000}),
    ):
        result = _run_async(strava.get_valid_token("athlete-1", db))

    assert result == "new-tok"
    db.table.return_value.update.assert_called_once()


def test_get_valid_token_returns_none_when_refresh_fails():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "old-tok", "refresh_token": "r1", "expires_at": 1.0}
    )
    with patch.object(
        strava, "refresh_oauth_token", AsyncMock(side_effect=HTTPException(status_code=401, detail="bad refresh"))
    ):
        assert _run_async(strava.get_valid_token("athlete-1", db)) is None


def test_get_activity_success():
    resp = _FakeResponse(status_code=200, json_data={"id": 123})
    with _patch_client(get=resp):
        result = _run_async(strava.get_activity(123, "tok"))
    assert result == {"id": 123}


def test_get_activity_raises_rate_limit_error_on_429():
    resp = _FakeResponse(status_code=429, headers={"Retry-After": "60"})
    with _patch_client(get=resp):
        with pytest.raises(strava.StravaRateLimitError) as exc_info:
            _run_async(strava.get_activity(123, "tok"))
    assert exc_info.value.retry_after == 60


def test_get_activity_raises_http_exception_on_error():
    resp = _FakeResponse(status_code=500, text="server error")
    with _patch_client(get=resp):
        with pytest.raises(HTTPException):
            _run_async(strava.get_activity(123, "tok"))


def test_get_activity_streams_returns_empty_on_404():
    resp = _FakeResponse(status_code=404)
    with _patch_client(get=resp):
        assert _run_async(strava.get_activity_streams(123, "tok")) == {}


def test_get_activity_streams_raises_rate_limit_on_429():
    resp = _FakeResponse(status_code=429, headers={})
    with _patch_client(get=resp):
        with pytest.raises(strava.StravaRateLimitError):
            _run_async(strava.get_activity_streams(123, "tok"))


def test_get_activity_streams_normalizes_list_response():
    resp = _FakeResponse(
        status_code=200,
        json_data=[{"type": "heartrate", "data": [1, 2]}, "not-a-dict", {"no_type": True}],
    )
    with _patch_client(get=resp):
        result = _run_async(strava.get_activity_streams(123, "tok"))
    assert "heartrate" in result
    assert len(result) == 1


def test_get_activity_streams_normalizes_dict_response():
    resp = _FakeResponse(status_code=200, json_data={"heartrate": {"data": [1, 2]}, "bad": "not-a-dict"})
    with _patch_client(get=resp):
        result = _run_async(strava.get_activity_streams(123, "tok"))
    assert result == {"heartrate": {"data": [1, 2]}}


def test_get_activity_streams_returns_empty_on_non_json():
    resp = _FakeResponse(status_code=200, json_error=True)
    with _patch_client(get=resp):
        assert _run_async(strava.get_activity_streams(123, "tok")) == {}


def test_get_activity_laps_swallows_all_errors():
    resp = _FakeResponse(status_code=500, text="down")
    with _patch_client(get=resp):
        assert _run_async(strava.get_activity_laps(123, "tok")) == []


def test_get_activity_laps_returns_list():
    resp = _FakeResponse(status_code=200, json_data=[{"lap_index": 1}])
    with _patch_client(get=resp):
        assert _run_async(strava.get_activity_laps(123, "tok")) == [{"lap_index": 1}]


def test_get_activity_laps_raises_rate_limit_which_is_swallowed_by_except():
    # get_activity_laps wraps everything (including StravaRateLimitError) in try/except -> [].
    resp = _FakeResponse(status_code=429, headers={})
    with _patch_client(get=resp):
        assert _run_async(strava.get_activity_laps(123, "tok")) == []


def test_get_athlete_strava_id_success():
    resp = _FakeResponse(status_code=200, json_data={"id": 987654})
    with _patch_client(get=resp):
        assert _run_async(strava.get_athlete_strava_id("tok")) == 987654


def test_get_athlete_strava_id_returns_none_on_error():
    resp = _FakeResponse(status_code=401, text="unauthorized")
    with _patch_client(get=resp):
        assert _run_async(strava.get_athlete_strava_id("tok")) is None


def test_get_athlete_strava_id_returns_none_when_id_missing():
    resp = _FakeResponse(status_code=200, json_data={"no_id": True})
    with _patch_client(get=resp):
        assert _run_async(strava.get_athlete_strava_id("tok")) is None


# ---------------------------------------------------------------------------
# DB-touching helpers (streams/laps persistence)
# ---------------------------------------------------------------------------


def test_load_stored_streams_dict_returns_empty_without_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert strava._load_stored_streams_dict(db, "w1") == {}


def test_load_stored_streams_dict_resolves_legacy_time_series():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"time_series": {"heartrate": [1, 2]}, "storage_path": None}
    )
    result = strava._load_stored_streams_dict(db, "w1")
    assert result == {"heartrate": {"data": [1, 2]}}


def test_upsert_activity_streams_noop_for_empty():
    db = MagicMock()
    strava._upsert_activity_streams(db, "w1", "athlete-1", {})
    db.table.assert_not_called()


def test_upsert_activity_streams_inserts_when_no_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    with patch("app.services.stream_storage.upload_time_series_gzip", return_value=("path", 100)):
        strava._upsert_activity_streams(db, "w1", "athlete-1", {"heartrate": {"data": [1, 2]}})
    db.table.return_value.insert.assert_called_once()


def test_upsert_activity_streams_updates_when_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "row-1"}
    )
    with patch("app.services.stream_storage.upload_time_series_gzip", return_value=("path", 100)):
        strava._upsert_activity_streams(db, "w1", "athlete-1", {"heartrate": {"data": [1, 2]}})
    db.table.return_value.update.assert_called_once()


def test_persist_activity_laps_noop_for_empty():
    db = MagicMock()
    strava._persist_activity_laps(db, "w1", "athlete-1", [])
    db.table.assert_not_called()


def test_persist_activity_laps_deletes_and_inserts():
    db = MagicMock()
    laps = [{"lap_index": 1, "distance": 500, "average_speed": 4.0}, "not-a-dict"]
    strava._persist_activity_laps(db, "w1", "athlete-1", laps)
    db.table.return_value.delete.assert_called_once()
    insert_call = db.table.return_value.insert.call_args[0][0]
    assert len(insert_call) == 1


def test_load_cached_laps_for_workout_returns_none_without_rows():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    assert strava._load_cached_laps_for_workout(db, "w1") is None


def test_load_cached_laps_for_workout_orders_by_lap_index():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[
            {"lap_index": 2, "raw_lap": {"n": 2}},
            {"lap_index": 1, "raw_lap": {"n": 1}},
        ]
    )
    result = strava._load_cached_laps_for_workout(db, "w1")
    assert [r["n"] for r in result] == [1, 2]


def test_load_cached_laps_for_workout_returns_none_on_bad_raw_lap():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"lap_index": 1, "raw_lap": "not-a-dict"}]
    )
    assert strava._load_cached_laps_for_workout(db, "w1") is None


# ---------------------------------------------------------------------------
# schedule_hydrate_streams_background / resolve_canonical_workout_for_strava_activity
# ---------------------------------------------------------------------------


def test_schedule_hydrate_streams_background_noop_without_running_loop():
    # Called from a sync context (no running event loop) -> should not raise.
    strava.schedule_hydrate_streams_background(MagicMock(), "athlete-1", "w1")


def test_schedule_hydrate_streams_background_schedules_task_when_loop_running():
    async def _run():
        with patch.object(strava, "_hydrate_streams_background", AsyncMock()):
            strava.schedule_hydrate_streams_background(MagicMock(), "athlete-1", "w1")
            await asyncio.sleep(0.01)

    _run_async(_run())


def test_resolve_canonical_workout_for_strava_activity_delegates():
    with patch.object(
        strava, "find_or_create_canonical_workout", AsyncMock(return_value=({"id": "w1"}, True))
    ) as mock_find:
        result = _run_async(
            strava.resolve_canonical_workout_for_strava_activity(
                MagicMock(), "athlete-1", "Run", datetime.now(timezone.utc), 1800, 111
            )
        )
    assert result == ({"id": "w1"}, True)
    mock_find.assert_called_once()


def test_sleep_if_delay_sleeps_when_true():
    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        _run_async(strava._sleep_if_delay(True))
    mock_sleep.assert_awaited_once_with(strava.STRAVA_BACKFILL_REQUEST_GAP_S)


def test_sleep_if_delay_noop_when_false():
    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        _run_async(strava._sleep_if_delay(False))
    mock_sleep.assert_not_awaited()


def test_finalize_strava_sync_recomputes_and_invalidates():
    db = MagicMock()
    with patch.object(strava, "recompute_workout_tss_for_athlete", AsyncMock()) as mock_recompute, patch.object(
        strava, "recalculate_tss_history", MagicMock()
    ) as mock_recalc, patch.object(strava, "invalidate_context_cache", MagicMock()) as mock_invalidate:
        _run_async(strava._finalize_strava_sync("athlete-1", db))

    mock_recompute.assert_awaited_once_with("athlete-1", db)
    mock_recalc.assert_called_once_with("athlete-1", db)
    mock_invalidate.assert_called_once_with("athlete-1")
