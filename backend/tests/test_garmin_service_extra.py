from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from app.services import garmin as garmin_service


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# login / resume_mfa
# ---------------------------------------------------------------------------


def test_login_success():
    fake_client = MagicMock()
    fake_client.login.return_value = ("ok", None)
    with patch.object(garmin_service, "Garmin", return_value=fake_client):
        result = garmin_service.login("user", "pass")
    assert result is fake_client


def test_login_needs_mfa_stores_pending_and_raises():
    fake_client = MagicMock()
    fake_client.login.return_value = ("needs_mfa", None)
    with patch.object(garmin_service, "Garmin", return_value=fake_client):
        with pytest.raises(garmin_service.GarminMfaRequired) as exc_info:
            garmin_service.login("user", "pass")
    state_token = exc_info.value.state_token
    assert garmin_service._pop_pending_mfa(state_token) is fake_client


def test_login_rate_limited():
    fake_client = MagicMock()
    fake_client.login.side_effect = GarminConnectTooManyRequestsError("429")
    with patch.object(garmin_service, "Garmin", return_value=fake_client):
        with pytest.raises(garmin_service.GarminRateLimitedError):
            garmin_service.login("user", "pass")


def test_login_auth_error():
    fake_client = MagicMock()
    fake_client.login.side_effect = GarminConnectAuthenticationError("bad creds")
    with patch.object(garmin_service, "Garmin", return_value=fake_client):
        with pytest.raises(garmin_service.GarminAuthError):
            garmin_service.login("user", "pass")


def test_resume_mfa_unknown_state_token():
    with pytest.raises(garmin_service.GarminAuthError):
        garmin_service.resume_mfa("nonexistent-token", "123456")


def test_resume_mfa_success():
    fake_client = MagicMock()
    garmin_service._store_pending_mfa("tok-1", fake_client)
    result = garmin_service.resume_mfa("tok-1", "123456")
    assert result is fake_client
    fake_client.resume_login.assert_called_once()


def test_resume_mfa_rate_limited():
    fake_client = MagicMock()
    fake_client.resume_login.side_effect = GarminConnectTooManyRequestsError("429")
    garmin_service._store_pending_mfa("tok-2", fake_client)
    with pytest.raises(garmin_service.GarminRateLimitedError):
        garmin_service.resume_mfa("tok-2", "123456")


def test_resume_mfa_auth_error():
    fake_client = MagicMock()
    fake_client.resume_login.side_effect = GarminConnectAuthenticationError("bad code")
    garmin_service._store_pending_mfa("tok-3", fake_client)
    with pytest.raises(garmin_service.GarminAuthError):
        garmin_service.resume_mfa("tok-3", "123456")


def test_prune_expired_mfa_removes_stale_entries():
    garmin_service._pending_mfa["stale-token"] = (MagicMock(), 0.0)  # already expired
    garmin_service._prune_expired_mfa()
    assert "stale-token" not in garmin_service._pending_mfa


# ---------------------------------------------------------------------------
# serialize_session / restore_session
# ---------------------------------------------------------------------------


def test_serialize_session_encrypts_dump():
    fake_client = MagicMock()
    fake_client.client.dumps.return_value = "session-blob"
    with patch("app.services.token_crypto.encrypt_token", return_value="encrypted-blob") as mock_encrypt:
        result = garmin_service.serialize_session(fake_client)
    mock_encrypt.assert_called_once_with("session-blob")
    assert result == "encrypted-blob"


def test_restore_session_rebuilds_client():
    fake_client = MagicMock()
    with patch("app.services.token_crypto.decrypt_token", return_value="plaintext"), patch.object(
        garmin_service, "Garmin", return_value=fake_client
    ):
        result = garmin_service.restore_session("blob")
    fake_client.client.loads.assert_called_once_with("plaintext")
    fake_client._load_profile_and_settings.assert_called_once()
    assert result is fake_client


# ---------------------------------------------------------------------------
# get_client_for_athlete
# ---------------------------------------------------------------------------


def test_get_client_for_athlete_no_row_returns_none():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert garmin_service.get_client_for_athlete("ath-1", db) is None


def test_get_client_for_athlete_empty_blob_returns_none():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": None}
    )
    assert garmin_service.get_client_for_athlete("ath-1", db) is None


def test_get_client_for_athlete_restore_success():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "blob"}
    )
    fake_client = MagicMock()
    with patch.object(garmin_service, "restore_session", return_value=fake_client):
        result = garmin_service.get_client_for_athlete("ath-1", db)
    assert result is fake_client


def test_get_client_for_athlete_restore_failure_returns_none():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "blob"}
    )
    with patch.object(garmin_service, "restore_session", side_effect=RuntimeError("bad key")):
        result = garmin_service.get_client_for_athlete("ath-1", db)
    assert result is None


# ---------------------------------------------------------------------------
# sync lock helpers
# ---------------------------------------------------------------------------


def test_claim_sync_lock_success():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.lt.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "row-1"}]
    )
    assert garmin_service._claim_sync_lock(db, "ath-1") is True


def test_claim_sync_lock_already_held():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.lt.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    assert garmin_service._claim_sync_lock(db, "ath-1") is False


def test_release_sync_lock_calls_update():
    db = MagicMock()
    garmin_service._release_sync_lock(db, "ath-1")
    db.table.assert_called_with("oauth_tokens")
    db.table.return_value.update.assert_called_once()


def test_cooldown_sync_lock_calls_update():
    db = MagicMock()
    garmin_service._cooldown_sync_lock(db, "ath-1", 1800)
    db.table.return_value.update.assert_called_once()


# ---------------------------------------------------------------------------
# persist_session
# ---------------------------------------------------------------------------


def test_persist_session_with_external_user_id():
    db = MagicMock()
    fake_client = MagicMock()
    with patch.object(garmin_service, "serialize_session", return_value="blob"):
        garmin_service.persist_session(db, "ath-1", fake_client, "garmin-user-1")
    payload = db.table.return_value.upsert.call_args[0][0]
    assert payload["external_user_id"] == "garmin-user-1"
    assert payload["access_token"] == "blob"


def test_persist_session_without_external_user_id():
    db = MagicMock()
    fake_client = MagicMock()
    with patch.object(garmin_service, "serialize_session", return_value="blob"):
        garmin_service.persist_session(db, "ath-1", fake_client)
    payload = db.table.return_value.upsert.call_args[0][0]
    assert "external_user_id" not in payload


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def test_round_int():
    assert garmin_service._round_int(None) is None
    assert garmin_service._round_int("not-a-number") is None
    assert garmin_service._round_int(3.6) == 4


def test_parse_garmin_datetime_formats():
    assert garmin_service._parse_garmin_datetime(None) is None
    assert garmin_service._parse_garmin_datetime("garbage") is None
    dt1 = garmin_service._parse_garmin_datetime("2026-05-20 10:00:00")
    assert dt1 == datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    dt2 = garmin_service._parse_garmin_datetime("2026-05-20T10:00:00.123456")
    assert dt2.year == 2026
    dt3 = garmin_service._parse_garmin_datetime("2026-05-20T10:00:00")
    assert dt3.year == 2026


def test_avg_pace_sec_km_from_speed():
    assert garmin_service._avg_pace_sec_km_from_speed(None) is None
    assert garmin_service._avg_pace_sec_km_from_speed("bad") is None
    assert garmin_service._avg_pace_sec_km_from_speed(0) is None
    assert garmin_service._avg_pace_sec_km_from_speed(-1) is None
    assert garmin_service._avg_pace_sec_km_from_speed(4.0) == 250


# ---------------------------------------------------------------------------
# build_workout_payload
# ---------------------------------------------------------------------------


def _activity(**overrides):
    base = {
        "activityId": 12345,
        "startTimeGMT": "2026-05-20 10:00:00",
        "duration": 3600,
        "activityType": {"typeKey": "running"},
        "elevationGain": 100,
        "calories": 500,
        "averageHR": 145,
        "maxHR": 172,
        "avgPower": 200,
        "normPower": 210,
        "averageSpeed": 3.0,
        "distance": 10000,
        "activityName": "Morning Run",
    }
    base.update(overrides)
    return base


def test_build_workout_payload_none_activity_id():
    assert garmin_service.build_workout_payload(_activity(activityId=None)) is None


def test_build_workout_payload_none_start_time():
    assert garmin_service.build_workout_payload(_activity(startTimeGMT=None)) is None


def test_build_workout_payload_full():
    payload = garmin_service.build_workout_payload(_activity())
    assert payload.external_id == "12345"
    assert payload.garmin_activity_id == 12345
    assert payload.workout_type == "run"
    assert payload.avg_pace_sec_km == 333


def test_build_workout_payload_elevation_fallback():
    payload = garmin_service.build_workout_payload(
        _activity(elevationGain=None, elevationCorrectedElevationGain=55)
    )
    assert payload.elevation_gain_m == 55.0


def test_build_workout_payload_calories_fallback():
    payload = garmin_service.build_workout_payload(_activity(calories=None, activeCalories=222))
    assert payload.calories == 222.0


def test_build_workout_payload_invalid_garmin_id():
    payload = garmin_service.build_workout_payload(_activity(activityId="not-an-int"))
    assert payload.garmin_activity_id is None


# ---------------------------------------------------------------------------
# _persist_activity_laps
# ---------------------------------------------------------------------------


def test_persist_activity_laps_empty_is_noop():
    db = MagicMock()
    garmin_service._persist_activity_laps(db, "w1", "ath-1", [])
    db.table.assert_not_called()


def test_persist_activity_laps_deletes_then_inserts():
    db = MagicMock()
    laps = [{"lap_index": 1, "start_index": 0, "end_index": 100, "elapsed_time": 60, "moving_time": 60}]
    garmin_service._persist_activity_laps(db, "w1", "ath-1", laps)
    db.table.return_value.delete.return_value.eq.assert_called_with("workout_id", "w1")


# ---------------------------------------------------------------------------
# _upsert_activity_streams
# ---------------------------------------------------------------------------


def test_upsert_activity_streams_empty_returns_false():
    db = MagicMock()
    assert garmin_service._upsert_activity_streams(db, "w1", "ath-1", {}) is False


def test_upsert_activity_streams_inserts_when_no_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    with patch.object(
        garmin_service.stream_storage, "upload_time_series_gzip", return_value=("path/to/file", 1024)
    ):
        result = garmin_service._upsert_activity_streams(db, "w1", "ath-1", {"heartrate": [140]})
    assert result is True
    db.table.return_value.insert.assert_called_once()


def test_upsert_activity_streams_updates_when_existing_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"id": "existing-row"}
    )
    with patch.object(
        garmin_service.stream_storage, "upload_time_series_gzip", return_value=("path/to/file", 1024)
    ):
        result = garmin_service._upsert_activity_streams(db, "w1", "ath-1", {"heartrate": [140]})
    assert result is True
    db.table.return_value.update.assert_called_once()


# ---------------------------------------------------------------------------
# _hr_samples_from_streams
# ---------------------------------------------------------------------------


def test_hr_samples_from_streams_not_a_list():
    assert garmin_service._hr_samples_from_streams({"heartrate": "not-a-list"}) == []


def test_hr_samples_from_streams_filters_invalid_and_out_of_range():
    streams = {"heartrate": [None, True, "abc", 10, 145.6, 300]}
    result = garmin_service._hr_samples_from_streams(streams)
    assert result == [146]  # only the in-range, valid numeric sample survives


# ---------------------------------------------------------------------------
# _update_workout_hr_zones_from_streams
# ---------------------------------------------------------------------------


def test_update_workout_hr_zones_no_hr_samples_is_noop():
    db = MagicMock()
    garmin_service._update_workout_hr_zones_from_streams(db, "w1", "ath-1", {})
    db.table.assert_not_called()


def test_update_workout_hr_zones_writes_zone_pcts_and_tss_when_missing():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
        SimpleNamespace(data={"max_hr": 190, "resting_hr": 50, "threshold_hr": 165, "gender": "male"}),
        SimpleNamespace(data={"tss": None}),
    ]
    streams = {"heartrate": [150] * 600}  # 10 min of Z3-ish HR
    with patch.object(garmin_service, "compute_zone_distribution", return_value={"Z3": 100.0}), patch.object(
        garmin_service, "compute_strain_score", return_value=42.0
    ), patch.object(garmin_service, "compute_hrss_from_zones", return_value=55.0):
        garmin_service._update_workout_hr_zones_from_streams(
            db, "w1", "ath-1", streams, duration_seconds=600, sport="run"
        )
    update_payload = db.table.return_value.update.call_args[0][0]
    assert update_payload["hr_zone_3_pct"] == 100
    assert update_payload["strain_score"] == 42.0
    assert update_payload["tss"] == 55.0


def test_update_workout_hr_zones_skips_tss_when_already_set():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
        SimpleNamespace(data={"max_hr": 190, "resting_hr": 50, "threshold_hr": 165, "gender": "male"}),
        SimpleNamespace(data={"tss": 88.0}),
    ]
    streams = {"heartrate": [150] * 600}
    with patch.object(garmin_service, "compute_zone_distribution", return_value={"Z3": 100.0}), patch.object(
        garmin_service, "compute_strain_score", return_value=42.0
    ), patch.object(garmin_service, "compute_hrss_from_zones") as mock_hrss:
        garmin_service._update_workout_hr_zones_from_streams(db, "w1", "ath-1", streams, sport="run")
    mock_hrss.assert_not_called()
    update_payload = db.table.return_value.update.call_args[0][0]
    assert "tss" not in update_payload


# ---------------------------------------------------------------------------
# _save_one_activity
# ---------------------------------------------------------------------------


def test_save_one_activity_no_payload_returns_false_false():
    result = _run_async(
        garmin_service._save_one_activity(MagicMock(), {"activityId": None}, "ath-1", MagicMock())
    )
    assert result == (False, False)


def test_save_one_activity_full_flow():
    activity = _activity()
    db = MagicMock()
    client = MagicMock()
    with patch.object(
        garmin_service, "process_and_save_workout", AsyncMock(return_value="workout-1")
    ), patch.object(
        garmin_service, "download_and_parse_fit", return_value=({"heartrate": [140]}, [{"lap_index": 1}])
    ), patch.object(
        garmin_service, "_upsert_activity_streams", return_value=True
    ) as mock_upsert, patch.object(
        garmin_service, "_update_workout_hr_zones_from_streams"
    ) as mock_zones, patch.object(
        garmin_service, "_persist_activity_laps"
    ) as mock_laps:
        result = _run_async(garmin_service._save_one_activity(client, activity, "ath-1", db))
    assert result == (True, True)
    mock_upsert.assert_called_once()
    mock_zones.assert_called_once()
    mock_laps.assert_called_once()


def test_save_one_activity_no_streams_saved_skips_zones():
    activity = _activity()
    db = MagicMock()
    client = MagicMock()
    with patch.object(
        garmin_service, "process_and_save_workout", AsyncMock(return_value="workout-1")
    ), patch.object(
        garmin_service, "download_and_parse_fit", return_value=({}, [])
    ), patch.object(
        garmin_service, "_upsert_activity_streams", return_value=False
    ), patch.object(
        garmin_service, "_update_workout_hr_zones_from_streams"
    ) as mock_zones, patch.object(
        garmin_service, "_persist_activity_laps"
    ) as mock_laps:
        result = _run_async(garmin_service._save_one_activity(client, activity, "ath-1", db))
    assert result == (True, False)
    mock_zones.assert_not_called()
    mock_laps.assert_not_called()


# ---------------------------------------------------------------------------
# sync_activities_for_athlete
# ---------------------------------------------------------------------------


def test_sync_activities_no_client_returns_zero_counts():
    with patch.object(garmin_service, "get_client_for_athlete", return_value=None):
        result = _run_async(
            garmin_service.sync_activities_for_athlete(
                "ath-1", MagicMock(), date(2026, 5, 1), date(2026, 5, 2)
            )
        )
    assert result == {"workouts": 0, "streams": 0, "connected": 0}


def test_sync_activities_rate_limited_on_list_persists_and_raises():
    fake_client = MagicMock()
    fake_client.get_activities_by_date.side_effect = GarminConnectTooManyRequestsError("429")
    db = MagicMock()
    with patch.object(
        garmin_service, "get_client_for_athlete", return_value=fake_client
    ), patch.object(garmin_service, "persist_session") as mock_persist:
        with pytest.raises(garmin_service.GarminRateLimitedError):
            _run_async(
                garmin_service.sync_activities_for_athlete(
                    "ath-1", db, date(2026, 5, 1), date(2026, 5, 2)
                )
            )
    mock_persist.assert_called_once()


def test_sync_activities_success_recomputes_tss():
    fake_client = MagicMock()
    fake_client.get_activities_by_date.return_value = [_activity(activityId=1), _activity(activityId=2)]
    db = MagicMock()
    with patch.object(
        garmin_service, "get_client_for_athlete", return_value=fake_client
    ), patch.object(garmin_service, "persist_session"), patch.object(
        garmin_service, "_save_one_activity", AsyncMock(return_value=(True, True))
    ), patch.object(
        garmin_service, "recompute_workout_tss_for_athlete", AsyncMock()
    ) as mock_recompute, patch.object(
        garmin_service, "recalculate_tss_history"
    ) as mock_recalc, patch.object(
        garmin_service, "invalidate_context_cache"
    ) as mock_invalidate, patch.object(
        garmin_service.asyncio, "sleep", AsyncMock()
    ):
        result = _run_async(
            garmin_service.sync_activities_for_athlete("ath-1", db, date(2026, 5, 1), date(2026, 5, 2))
        )
    assert result == {"workouts": 2, "streams": 2, "connected": 1}
    mock_recompute.assert_awaited_once()
    mock_recalc.assert_called_once()
    mock_invalidate.assert_called_once()


def test_sync_activities_rate_limited_mid_pass_stops_and_reraises():
    fake_client = MagicMock()
    fake_client.get_activities_by_date.return_value = [_activity(activityId=1), _activity(activityId=2)]
    db = MagicMock()
    with patch.object(
        garmin_service, "get_client_for_athlete", return_value=fake_client
    ), patch.object(garmin_service, "persist_session"), patch.object(
        garmin_service,
        "_save_one_activity",
        AsyncMock(side_effect=garmin_service.GarminRateLimitedError("429")),
    ), patch.object(
        garmin_service, "recompute_workout_tss_for_athlete", AsyncMock()
    ), patch.object(
        garmin_service, "recalculate_tss_history"
    ), patch.object(garmin_service, "invalidate_context_cache"), patch.object(
        garmin_service.asyncio, "sleep", AsyncMock()
    ):
        with pytest.raises(garmin_service.GarminRateLimitedError):
            _run_async(
                garmin_service.sync_activities_for_athlete(
                    "ath-1", db, date(2026, 5, 1), date(2026, 5, 2)
                )
            )


# ---------------------------------------------------------------------------
# _daily_biometrics_from_garmin / _parse_epoch_ms
# ---------------------------------------------------------------------------


def test_daily_biometrics_from_garmin_all_none_returns_none():
    assert garmin_service._daily_biometrics_from_garmin(date(2026, 5, 20), None, None, None) is None


def test_daily_biometrics_from_garmin_builds_payload():
    sleep = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 28800,
            "deepSleepSeconds": 3600,
            "lightSleepSeconds": 18000,
            "remSleepSeconds": 5400,
            "awakeSleepSeconds": 1800,
            "sleepStartTimestampGMT": 1_780_000_000_000,
            "sleepEndTimestampGMT": 1_780_028_800_000,
        }
    }
    hrv = {"hrvSummary": {"lastNightAvg": 55}}
    heart_rates = {"restingHeartRate": 48}
    payload = garmin_service._daily_biometrics_from_garmin(date(2026, 5, 20), sleep, hrv, heart_rates)
    assert payload is not None
    assert payload.resting_hr == 48
    assert payload.hrv_rmssd == 55
    assert payload.sleep_duration_min == 480


def test_parse_epoch_ms_invalid_returns_none():
    assert garmin_service._parse_epoch_ms(None) is None
    assert garmin_service._parse_epoch_ms("not-a-number") is None


def test_parse_epoch_ms_valid():
    result = garmin_service._parse_epoch_ms(1_780_000_000_000)
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# fetch_and_store_biometrics_for_day
# ---------------------------------------------------------------------------


def test_fetch_and_store_biometrics_for_day_success():
    client = MagicMock()
    client.get_sleep_data.return_value = {
        "dailySleepDTO": {"sleepTimeSeconds": 28800}
    }
    client.get_hrv_data.return_value = {"hrvSummary": {"lastNightAvg": 55}}
    client.get_heart_rates.return_value = {"restingHeartRate": 48}
    db = MagicMock()
    with patch.object(garmin_service, "process_and_save_biometrics") as mock_save:
        result = _run_async(
            garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, date(2026, 5, 20))
        )
    assert result is True
    mock_save.assert_called_once()


def test_fetch_and_store_biometrics_for_day_no_usable_data_returns_false():
    client = MagicMock()
    client.get_sleep_data.return_value = None
    client.get_hrv_data.return_value = None
    client.get_heart_rates.return_value = None
    db = MagicMock()
    with patch.object(garmin_service, "process_and_save_biometrics") as mock_save:
        result = _run_async(
            garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, date(2026, 5, 20))
        )
    assert result is False
    mock_save.assert_not_called()


def test_fetch_and_store_biometrics_for_day_rate_limited_on_sleep():
    client = MagicMock()
    client.get_sleep_data.side_effect = GarminConnectTooManyRequestsError("429")
    with pytest.raises(garmin_service.GarminRateLimitedError):
        _run_async(
            garmin_service.fetch_and_store_biometrics_for_day(
                "ath-1", MagicMock(), client, date(2026, 5, 20)
            )
        )


def test_fetch_and_store_biometrics_for_day_swallows_non_rate_limit_errors():
    client = MagicMock()
    client.get_sleep_data.side_effect = RuntimeError("transient")
    client.get_hrv_data.return_value = {"hrvSummary": {"lastNightAvg": 55}}
    client.get_heart_rates.return_value = None
    with patch.object(garmin_service, "process_and_save_biometrics"):
        result = _run_async(
            garmin_service.fetch_and_store_biometrics_for_day(
                "ath-1", MagicMock(), client, date(2026, 5, 20)
            )
        )
    assert result is True  # hrv alone is enough for has_any


# ---------------------------------------------------------------------------
# sync_biometrics_for_athlete
# ---------------------------------------------------------------------------


def test_sync_biometrics_no_client_returns_zero():
    with patch.object(garmin_service, "get_client_for_athlete", return_value=None):
        result = _run_async(
            garmin_service.sync_biometrics_for_athlete(
                "ath-1", MagicMock(), date(2026, 5, 1), date(2026, 5, 2)
            )
        )
    assert result == 0


def test_sync_biometrics_success_counts_days():
    fake_client = MagicMock()
    db = MagicMock()
    with patch.object(
        garmin_service, "get_client_for_athlete", return_value=fake_client
    ), patch.object(
        garmin_service, "fetch_and_store_biometrics_for_day", AsyncMock(return_value=True)
    ), patch.object(garmin_service, "persist_session"), patch.object(
        garmin_service.asyncio, "sleep", AsyncMock()
    ):
        result = _run_async(
            garmin_service.sync_biometrics_for_athlete("ath-1", db, date(2026, 5, 1), date(2026, 5, 2))
        )
    assert result == 2  # two days inclusive


def test_sync_biometrics_rate_limited_stops_and_reraises():
    fake_client = MagicMock()
    db = MagicMock()
    with patch.object(
        garmin_service, "get_client_for_athlete", return_value=fake_client
    ), patch.object(
        garmin_service,
        "fetch_and_store_biometrics_for_day",
        AsyncMock(side_effect=garmin_service.GarminRateLimitedError("429")),
    ), patch.object(garmin_service, "persist_session"), patch.object(
        garmin_service.asyncio, "sleep", AsyncMock()
    ):
        with pytest.raises(garmin_service.GarminRateLimitedError):
            _run_async(
                garmin_service.sync_biometrics_for_athlete(
                    "ath-1", db, date(2026, 5, 1), date(2026, 5, 2)
                )
            )


# ---------------------------------------------------------------------------
# backfill_historical_data
# ---------------------------------------------------------------------------


def test_backfill_historical_data_success():
    with patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock(return_value={"workouts": 3, "streams": 2})
    ), patch.object(garmin_service, "sync_biometrics_for_athlete", AsyncMock(return_value=5)):
        result = _run_async(garmin_service.backfill_historical_data("ath-1", MagicMock(), days=30))
    assert result["workouts"] == 3
    assert result["biometrics"] == 5
    assert "rate_limited" not in result


def test_backfill_historical_data_rate_limited_keeps_partial_progress():
    with patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock(return_value={"workouts": 1, "streams": 1})
    ), patch.object(
        garmin_service,
        "sync_biometrics_for_athlete",
        AsyncMock(side_effect=garmin_service.GarminRateLimitedError("429")),
    ):
        result = _run_async(garmin_service.backfill_historical_data("ath-1", MagicMock(), days=30))
    assert result["rate_limited"] is True
    assert result["workouts"] == 1


def test_backfill_historical_data_clamps_days():
    with patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock(return_value={"workouts": 0, "streams": 0})
    ), patch.object(garmin_service, "sync_biometrics_for_athlete", AsyncMock(return_value=0)):
        result = _run_async(garmin_service.backfill_historical_data("ath-1", MagicMock(), days=9999))
    assert result["days"] == 365


# ---------------------------------------------------------------------------
# _poll_one_athlete / poll_tick
# ---------------------------------------------------------------------------


def test_poll_one_athlete_lock_held_by_another_replica_skips():
    db = MagicMock()
    with patch.object(garmin_service, "_claim_sync_lock", return_value=False), patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock()
    ) as mock_sync:
        _run_async(garmin_service._poll_one_athlete("ath-1", db))
    mock_sync.assert_not_called()


def test_poll_one_athlete_success_releases_lock():
    db = MagicMock()
    with patch.object(garmin_service, "_claim_sync_lock", return_value=True), patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock()
    ), patch.object(garmin_service, "sync_biometrics_for_athlete", AsyncMock()), patch.object(
        garmin_service, "_release_sync_lock"
    ) as mock_release, patch.object(garmin_service, "_cooldown_sync_lock") as mock_cooldown:
        _run_async(garmin_service._poll_one_athlete("ath-1", db))
    mock_release.assert_called_once()
    mock_cooldown.assert_not_called()


def test_poll_one_athlete_rate_limited_applies_cooldown():
    db = MagicMock()
    with patch.object(garmin_service, "_claim_sync_lock", return_value=True), patch.object(
        garmin_service,
        "sync_activities_for_athlete",
        AsyncMock(side_effect=garmin_service.GarminRateLimitedError("429")),
    ), patch.object(garmin_service, "_release_sync_lock") as mock_release, patch.object(
        garmin_service, "_cooldown_sync_lock"
    ) as mock_cooldown:
        _run_async(garmin_service._poll_one_athlete("ath-1", db))
    mock_cooldown.assert_called_once_with(db, "ath-1", garmin_service.GARMIN_RATE_LIMIT_COOLDOWN_SEC)
    mock_release.assert_not_called()


def test_poll_one_athlete_swallows_unexpected_errors():
    db = MagicMock()
    with patch.object(garmin_service, "_claim_sync_lock", return_value=True), patch.object(
        garmin_service, "sync_activities_for_athlete", AsyncMock(side_effect=RuntimeError("boom"))
    ), patch.object(garmin_service, "_release_sync_lock") as mock_release:
        _run_async(garmin_service._poll_one_athlete("ath-1", db))  # should not raise
    mock_release.assert_called_once()


def test_poll_tick_processes_each_connected_athlete():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "a1"}, {"athlete_id": "a2"}]
    )
    with patch.object(garmin_service, "_poll_one_athlete", AsyncMock()) as mock_poll:
        count = _run_async(garmin_service.poll_tick(db))
    assert count == 2
    assert mock_poll.await_count == 2


def test_poll_tick_no_athletes_returns_zero():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    with patch.object(garmin_service, "_poll_one_athlete", AsyncMock()) as mock_poll:
        count = _run_async(garmin_service.poll_tick(db))
    assert count == 0
    mock_poll.assert_not_called()
