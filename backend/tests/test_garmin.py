from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import fitdecode
import pytest
from garminconnect.exceptions import GarminConnectTooManyRequestsError

from app.services import garmin as garmin_service


def _run_async(coro):
    # No pytest-asyncio in this project; matches tests/test_intervals_icu.py's helper.
    try:
        return asyncio.run(coro)
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_map_garmin_connect_sport_common_keys():
    assert garmin_service.map_garmin_connect_sport("running") == "run"
    assert garmin_service.map_garmin_connect_sport("trail_running") == "run"
    assert garmin_service.map_garmin_connect_sport("cycling") == "bike"
    assert garmin_service.map_garmin_connect_sport("indoor_cycling") == "bike"
    assert garmin_service.map_garmin_connect_sport("open_water_swimming") == "swim"
    assert garmin_service.map_garmin_connect_sport("strength_training") == "strength"
    assert garmin_service.map_garmin_connect_sport("indoor_rowing") == "row"
    assert garmin_service.map_garmin_connect_sport("yoga") == "mobility"
    assert garmin_service.map_garmin_connect_sport("hiking") == "other"


def test_map_garmin_connect_sport_unknown_and_none():
    assert garmin_service.map_garmin_connect_sport("totally_made_up") == "other"
    assert garmin_service.map_garmin_connect_sport(None) == "other"
    assert garmin_service.map_garmin_connect_sport("  Cycling  ") == "bike"


def test_build_workout_payload_from_activity_summary():
    activity = {
        "activityId": 987654321,
        "activityName": "Morning Ride",
        "startTimeGMT": "2026-06-18 10:00:00",
        "duration": 3600.4,
        "distance": 40233.5,
        "elevationGain": 412.5,
        "calories": 850.0,
        "avgPower": 210.6,
        "normPower": 225.2,  # real Garmin Connect field name (not "normalizedPower")
        "averageHR": 148.7,
        "maxHR": 172.1,
        "averageSpeed": 11.175,  # m/s → ~89 s/km
        "activityType": {"typeKey": "cycling"},
    }

    payload = garmin_service.build_workout_payload(activity)

    assert payload is not None
    assert payload.source == "garmin"
    assert payload.external_id == "987654321"
    assert payload.garmin_activity_id == 987654321
    assert payload.workout_type == "bike"
    assert payload.start_time == datetime(2026, 6, 18, 10, 0, tzinfo=timezone.utc)
    assert payload.ended_at == datetime(2026, 6, 18, 11, 0, tzinfo=timezone.utc)
    assert payload.duration_seconds == 3600
    assert payload.distance_m == 40233.5
    assert payload.elevation_gain_m == 412.5
    assert payload.calories == 850.0
    assert payload.average_power == 211
    assert payload.normalized_power == 225
    assert payload.average_hr == 149
    assert payload.max_hr == 172
    assert payload.avg_pace_sec_km == 89
    assert payload.title == "Morning Ride"


def test_build_workout_payload_requires_id_and_start():
    assert garmin_service.build_workout_payload({"startTimeGMT": "2026-06-18 10:00:00"}) is None
    assert garmin_service.build_workout_payload({"activityId": 1}) is None


def test_daily_biometrics_from_garmin():
    day = date(2026, 6, 18)
    sleep_start_ms = int(datetime(2026, 6, 17, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)
    sleep_end_ms = int(datetime(2026, 6, 18, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
    sleep = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 8 * 3600,
            "deepSleepSeconds": 90 * 60,
            "remSleepSeconds": 120 * 60,
            "lightSleepSeconds": 270 * 60,
            "awakeSleepSeconds": 30 * 60,
            "sleepStartTimestampGMT": sleep_start_ms,
            "sleepEndTimestampGMT": sleep_end_ms,
            "avgSpO2": 96.0,
        },
        "skinTempDataExists": True,
        "avgSkinTempDeviationC": 0.3,
    }
    hrv = {"hrvSummary": {"lastNightAvg": 62.5}}
    heart_rates = {"restingHeartRate": 48.2}

    bio = garmin_service._daily_biometrics_from_garmin(day, sleep, hrv, heart_rates)

    assert bio is not None
    assert bio.date == day
    assert bio.source == "garmin"
    assert bio.external_id == "garmin:2026-06-18"
    assert bio.hrv_rmssd == 62.5
    assert bio.resting_hr == 48
    assert bio.spo2_pct == 96.0
    assert bio.skin_temp_deviation_c == 0.3
    assert bio.sleep_duration_min == 480
    assert bio.sleep_deep_pct == 18.8
    assert bio.sleep_rem_pct == 25.0
    assert bio.sleep_light_pct == 56.2
    assert bio.sleep_awake_pct == 6.2
    assert bio.sleep_bedtime == datetime(2026, 6, 17, 23, 0, tzinfo=timezone.utc)
    assert bio.sleep_wakeup == datetime(2026, 6, 18, 7, 0, tzinfo=timezone.utc)


def test_daily_biometrics_from_garmin_returns_none_when_empty():
    assert garmin_service._daily_biometrics_from_garmin(date(2026, 6, 18), {}, {}, {}) is None


def test_daily_biometrics_from_garmin_ignores_skin_temp_before_calibration():
    """skinTempDataExists=False means the device hasn't finished baselining yet
    (~2-3 weeks) -- avgSkinTempDeviationC (often a stale 0.0) shouldn't be trusted."""
    sleep = {
        "dailySleepDTO": {"sleepTimeSeconds": 8 * 3600},
        "skinTempDataExists": False,
        "avgSkinTempDeviationC": 0.0,
    }

    bio = garmin_service._daily_biometrics_from_garmin(date(2026, 6, 18), sleep, {}, {})

    assert bio is not None
    assert bio.skin_temp_deviation_c is None


def test_daily_biometrics_from_garmin_spo2_only():
    day = date(2026, 6, 18)
    sleep = {"dailySleepDTO": {"avgSpO2": 94.0}}

    bio = garmin_service._daily_biometrics_from_garmin(day, sleep, {}, {})

    assert bio is not None
    assert bio.spo2_pct == 94.0
    assert bio.hrv_rmssd is None
    assert bio.resting_hr is None


def test_extract_fit_bytes_from_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("activity.fit", b"FITDATA")
        zf.writestr("readme.txt", b"ignore me")
    fit_bytes = garmin_service._extract_fit_bytes(buf.getvalue())
    assert fit_bytes == b"FITDATA"


def test_extract_fit_bytes_returns_none_without_fit_entry():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", b"no fit here")
    assert garmin_service._extract_fit_bytes(buf.getvalue()) is None


def _fake_fit_header_bytes(body: bytes = b"restofdata") -> bytes:
    """
    A minimal, structurally-plausible FIT file: the ".FIT" data-type
    signature lives at byte offset 8 (after header_size(1) +
    protocol_version(1) + profile_version(2) + data_size(4)), not offset 0.
    """
    return bytes([14, 0x10]) + b"\x00\x00" + b"\x00\x00\x00\x00" + b".FIT" + body


def test_extract_fit_bytes_detects_bare_fit_file_not_wrapped_in_zip():
    """
    Some activities (e.g. manually-entered) return a bare, non-zip FIT file
    for the ORIGINAL download format. Regression test for a real bug: the
    ".FIT" signature was checked at byte offset 0 instead of 8, so this path
    never actually detected a valid bare FIT file.
    """
    raw = _fake_fit_header_bytes()
    assert garmin_service._extract_fit_bytes(raw) == raw


def test_extract_fit_bytes_returns_none_for_non_fit_non_zip_bytes():
    assert garmin_service._extract_fit_bytes(b"not a fit file, not a zip either") is None


class _FakeFitFrame:
    def __init__(self, name: str, values: dict):
        self.frame_type = fitdecode.FIT_FRAME_DATA
        self.name = name
        self._values = values

    def get_value(self, key, fallback=None):
        return self._values.get(key, fallback)


def test_download_and_parse_fit_shapes_strava_streams_and_laps():
    t0 = datetime(2026, 6, 18, 10, 0, 0, tzinfo=timezone.utc)
    frames = [
        _FakeFitFrame(
            "record",
            {
                "timestamp": t0,
                "heart_rate": 140,
                "power": 200,
                "cadence": 90,
                "enhanced_speed": 10.0,
                "enhanced_altitude": 100.0,
                "distance": 0.0,
                "position_lat": int(40.0 / garmin_service._SEMICIRCLE_TO_DEG),
                "position_long": int(-74.0 / garmin_service._SEMICIRCLE_TO_DEG),
            },
        ),
        _FakeFitFrame(
            "record",
            {
                "timestamp": t0 + timedelta(seconds=1),
                "heart_rate": 145,
                "power": 210,
                "cadence": 92,
                "enhanced_speed": 10.5,
                "enhanced_altitude": 101.0,
                "distance": 10.5,
                "position_lat": int(40.001 / garmin_service._SEMICIRCLE_TO_DEG),
                "position_long": int(-74.001 / garmin_service._SEMICIRCLE_TO_DEG),
            },
        ),
        _FakeFitFrame(
            "lap",
            {
                "total_elapsed_time": 1.0,
                "total_timer_time": 1.0,
                "total_distance": 10.5,
                "avg_heart_rate": 142,
                "max_heart_rate": 145,
                "avg_power": 205,
                "avg_cadence": 91,
                "avg_speed": 10.25,
                "total_ascent": 1.0,
            },
        ),
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("activity.fit", b"fake-fit")

    client = MagicMock()
    client.download_activity.return_value = zip_buf.getvalue()

    class _FakeFitReader:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return frames

        def __exit__(self, *_exc):
            return False

    with patch.object(garmin_service.fitdecode, "FitReader", _FakeFitReader):
        streams, laps = garmin_service.download_and_parse_fit(client, "123")

    assert streams["time"] == [0, 1]
    assert streams["heartrate"] == [140, 145]
    assert streams["watts"] == [200, 210]
    assert streams["cadence"] == [90, 92]
    assert streams["velocity_smooth"] == [10.0, 10.5]
    assert streams["altitude"] == [100.0, 101.0]
    assert streams["distance"] == [0.0, 10.5]
    assert len(streams["latlng"]) == 2
    assert streams["latlng"][0][0] == pytest.approx(40.0, abs=0.01)
    assert streams["latlng"][0][1] == pytest.approx(-74.0, abs=0.01)

    assert len(laps) == 1
    assert laps[0]["lap_index"] == 0
    assert laps[0]["start_index"] == 0
    assert laps[0]["end_index"] == 1
    assert laps[0]["elapsed_time"] == 1
    assert laps[0]["average_heartrate"] == 142
    assert laps[0]["average_watts"] == 205


def test_download_and_parse_fit_omits_null_latlng_entries():
    """
    Records before GPS lock have no position_lat/long. Strava's stream
    contract (assumed by every frontend consumer, e.g. GpsTrace.svelte,
    which destructures every latlng entry as [lat, lng] with no null
    check) only ever contains valid points — never None placeholders.
    Regression test for a real bug: a None-padded latlng crashed the map.
    """
    t0 = datetime(2026, 6, 18, 10, 0, 0, tzinfo=timezone.utc)
    frames = [
        _FakeFitFrame(
            "record",
            {
                "timestamp": t0,
                "heart_rate": 130,
                "position_lat": None,
                "position_long": None,
            },
        ),
        _FakeFitFrame(
            "record",
            {
                "timestamp": t0 + timedelta(seconds=1),
                "heart_rate": 132,
                "position_lat": None,
                "position_long": None,
            },
        ),
        _FakeFitFrame(
            "record",
            {
                "timestamp": t0 + timedelta(seconds=2),
                "heart_rate": 135,
                "position_lat": int(40.0 / garmin_service._SEMICIRCLE_TO_DEG),
                "position_long": int(-74.0 / garmin_service._SEMICIRCLE_TO_DEG),
            },
        ),
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("activity.fit", b"fake-fit")

    client = MagicMock()
    client.download_activity.return_value = zip_buf.getvalue()

    class _FakeFitReader:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return frames

        def __exit__(self, *_exc):
            return False

    with patch.object(garmin_service.fitdecode, "FitReader", _FakeFitReader):
        streams, _laps = garmin_service.download_and_parse_fit(client, "123")

    # 3 heartrate samples (one per record, still 1:1 with time)...
    assert streams["heartrate"] == [130, 132, 135]
    # ...but only 1 latlng point: no None entries, and not padded to length 3.
    assert streams["latlng"] == [[pytest.approx(40.0, abs=0.01), pytest.approx(-74.0, abs=0.01)]]
    assert None not in streams["latlng"]


def test_download_and_parse_fit_omits_latlng_key_when_no_gps_at_all():
    t0 = datetime(2026, 6, 18, 10, 0, 0, tzinfo=timezone.utc)
    frames = [
        _FakeFitFrame(
            "record",
            {"timestamp": t0, "heart_rate": 130, "position_lat": None, "position_long": None},
        ),
    ]
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("activity.fit", b"fake-fit")
    client = MagicMock()
    client.download_activity.return_value = zip_buf.getvalue()

    class _FakeFitReader:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return frames

        def __exit__(self, *_exc):
            return False

    with patch.object(garmin_service.fitdecode, "FitReader", _FakeFitReader):
        streams, _laps = garmin_service.download_and_parse_fit(client, "123")

    assert "latlng" not in streams


def test_download_and_parse_fit_returns_empty_when_download_fails():
    client = MagicMock()
    client.download_activity.side_effect = RuntimeError("no file")
    streams, laps = garmin_service.download_and_parse_fit(client, "999")
    assert streams == {}
    assert laps == []


def test_download_and_parse_fit_propagates_rate_limit():
    """
    A 429 is not "no FIT data for this activity" — it must stop the caller,
    not be swallowed like every other download failure (garminconnect never
    retries 429s itself; see the module docstring on GARMIN_RATE_LIMIT_COOLDOWN_SEC).
    """
    client = MagicMock()
    client.download_activity.side_effect = GarminConnectTooManyRequestsError("429")
    with pytest.raises(garmin_service.GarminRateLimitedError):
        garmin_service.download_and_parse_fit(client, "999")


def test_fetch_and_store_biometrics_for_day_propagates_rate_limit_without_trying_rest():
    client = MagicMock()
    client.get_sleep_data.side_effect = GarminConnectTooManyRequestsError("429")
    client.get_hrv_data.return_value = {}
    client.get_heart_rates.return_value = {}

    async def run():
        with pytest.raises(garmin_service.GarminRateLimitedError):
            await garmin_service.fetch_and_store_biometrics_for_day(
                "athlete-1", MagicMock(), client, date(2026, 6, 18)
            )

    _run_async(run())

    # Sleep 429'd first — hrv/heart_rates for this day must not be attempted.
    client.get_hrv_data.assert_not_called()
    client.get_heart_rates.assert_not_called()


def test_poll_one_athlete_applies_cooldown_on_rate_limit(monkeypatch):
    """
    On a 429, the poll loop must hold the athlete's sync lock past its normal
    duration (GARMIN_RATE_LIMIT_COOLDOWN_SEC) instead of releasing it
    immediately — otherwise the very next poll tick retries into the same
    rate limit.
    """
    monkeypatch.setattr(garmin_service, "_claim_sync_lock", lambda db, athlete_id: True)

    async def _raise_rate_limited(*_a, **_k):
        raise garmin_service.GarminRateLimitedError("429")

    monkeypatch.setattr(garmin_service, "sync_activities_for_athlete", _raise_rate_limited)

    cooldown_calls = []
    release_calls = []
    monkeypatch.setattr(
        garmin_service,
        "_cooldown_sync_lock",
        lambda db, athlete_id, seconds: cooldown_calls.append((athlete_id, seconds)),
    )
    monkeypatch.setattr(
        garmin_service, "_release_sync_lock", lambda db, athlete_id: release_calls.append(athlete_id)
    )

    _run_async(garmin_service._poll_one_athlete("athlete-1", MagicMock()))

    assert cooldown_calls == [("athlete-1", garmin_service.GARMIN_RATE_LIMIT_COOLDOWN_SEC)]
    assert release_calls == []


def test_token_crypto_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.services import token_crypto

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", key)
    token_crypto._fernet.cache_clear()

    encrypted = token_crypto.encrypt_token('{"di_token":"abc"}')
    assert encrypted.startswith("gAAAAA")
    assert token_crypto.decrypt_token(encrypted) == '{"di_token":"abc"}'
    # Legacy plaintext still readable
    assert token_crypto.decrypt_token('{"di_token":"plain"}') == '{"di_token":"plain"}'
    token_crypto._fernet.cache_clear()


class _FakeUpsertDB:
    """Fake covering persist_session's `.table(...).upsert(payload, ...).execute()` call."""

    def __init__(self):
        self.payload: dict | None = None

    def table(self, _name):
        return self

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        return self

    def execute(self):
        return None


class _FakeSelectDB:
    """Fake covering get_client_for_athlete's `.table(...).select(...).eq(...).maybe_single().execute()` call."""

    def __init__(self, row: dict | None):
        self._row = row

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return MagicMock(data=self._row)


def test_garmin_session_encrypted_at_rest_end_to_end(monkeypatch):
    """
    persist_session()/get_client_for_athlete() must actually encrypt/decrypt
    through app.services.token_crypto — not just the isolated Fernet helpers.
    Guards against the encryption plumbing being wired up but unused, or vice
    versa (e.g. storing plaintext while claiming it's encrypted).
    """
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.services import token_crypto

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", key)
    token_crypto._fernet.cache_clear()

    secret_session_json = '{"di_token": "secret-jwt-abc", "di_refresh_token": "secret-refresh-xyz"}'
    fake_inner = MagicMock()
    fake_inner.dumps.return_value = secret_session_json
    fake_client = MagicMock()
    fake_client.client = fake_inner

    db = _FakeUpsertDB()
    garmin_service.persist_session(db, "athlete-1", fake_client, "display-name-1")

    stored_blob = db.payload["access_token"]
    assert "secret-jwt-abc" not in stored_blob, "plaintext session token leaked into the DB row"
    assert stored_blob.startswith("gAAAAA"), "stored blob is not Fernet ciphertext"

    # Restore path: decrypt_token must recover exactly what was serialized.
    assert token_crypto.decrypt_token(stored_blob) == secret_session_json

    restore_db = _FakeSelectDB(row={"access_token": stored_blob})
    with patch.object(garmin_service.Garmin, "_load_profile_and_settings", lambda self: None):
        client = garmin_service.get_client_for_athlete("athlete-1", restore_db)
    assert client is not None
    # get_client_for_athlete restores through the real client.Client.loads(),
    # so check its effect (parsed tokens) rather than mocking it away.
    assert client.client.di_token == "secret-jwt-abc"
    assert client.client.di_refresh_token == "secret-refresh-xyz"

    token_crypto._fernet.cache_clear()


def test_garmin_session_restore_fails_closed_on_wrong_key(monkeypatch):
    """A blob encrypted under a since-rotated key must fail closed (None), not raise."""
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.services import token_crypto

    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()
    stored_blob = token_crypto.encrypt_token('{"di_token": "abc"}')

    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_crypto._fernet.cache_clear()

    db = _FakeSelectDB(row={"access_token": stored_blob})
    with patch.object(garmin_service.Garmin, "_load_profile_and_settings", lambda self: None):
        client = garmin_service.get_client_for_athlete("athlete-1", db)
    assert client is None

    token_crypto._fernet.cache_clear()


def test_mfa_store_roundtrip_in_process():
    client = MagicMock(spec=[])
    token = "test-mfa-token"
    garmin_service._store_pending_mfa(token, client)
    assert garmin_service._pop_pending_mfa(token) is client
    assert garmin_service._pop_pending_mfa(token) is None


def test_mfa_store_expires_after_ttl(monkeypatch):
    client = MagicMock(spec=[])
    token = "expiring-mfa-token"
    garmin_service._store_pending_mfa(token, client)
    # Simulate TTL elapsing without waiting in real time.
    future = garmin_service.time.monotonic() + garmin_service._MFA_TTL_SECONDS + 1
    monkeypatch.setattr(garmin_service.time, "monotonic", lambda: future)
    assert garmin_service._pop_pending_mfa(token) is None


# --------------------------------------------------------------------------
# _update_workout_hr_zones_from_streams: recording-gap duration + TSS backfill
# --------------------------------------------------------------------------

class _FakeZonesDB:
    """
    Fake covering `_update_workout_hr_zones_from_streams`'s three call shapes:
    `.table("athletes").select(...).eq(...).maybe_single().execute()`,
    `.table("workouts").select("tss").eq("id", ...).maybe_single().execute()`,
    and `.table("workouts").update(...).eq("id", ...).execute()`.
    """

    def __init__(self, athlete_row: dict, existing_tss):
        self._athlete_row = athlete_row
        self._existing_tss = existing_tss
        self._table = None
        self._select_cols = None
        self.update_payload: dict | None = None

    def table(self, name):
        self._table = name
        return self

    def select(self, cols=None):
        self._select_cols = cols
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def execute(self):
        if self._table == "athletes":
            return MagicMock(data=self._athlete_row)
        if self._table == "workouts" and self._select_cols == "tss":
            return MagicMock(data={"tss": self._existing_tss})
        return MagicMock(data=None)


_TEST_ATHLETE_ROW = {
    "lthr": None,
    "threshold_hr": 165,
    "max_hr": 190,
    "resting_hr": 50,
    "threshold_hr_source": "manual",
    "hr_zone_method": "lthr",
    "gender": "male",
}


def test_hr_zones_use_workout_duration_not_truncated_stream_length(monkeypatch):
    """
    A device that stops recording mid-activity (and is manually restarted)
    produces a stream far shorter than the workout's real duration. Zone
    minutes (and everything derived from them — strain, TSS) must scale
    against the workout's actual duration_seconds, not len(hr_samples),
    or a 26-minute effort with a 9-minute recording gets scored as if it
    were only 9 minutes long.
    """
    from app.services.algorithms import compute_strain_score

    monkeypatch.setattr(
        garmin_service, "compute_zone_distribution", lambda samples, zones: {"Z3": 100.0}
    )

    # 9 minutes of recorded samples; the workout actually took 26 minutes.
    streams = {"heartrate": [165] * 540}
    db = _FakeZonesDB(_TEST_ATHLETE_ROW, existing_tss=0.0)

    garmin_service._update_workout_hr_zones_from_streams(
        db, "workout-1", "athlete-1", streams, duration_seconds=1560, sport="row",
    )

    assert db.update_payload is not None
    expected_strain = compute_strain_score({3: 26.0}, sport="row")
    assert db.update_payload["strain_score"] == expected_strain
    # The buggy (stream-length) computation would have used 9.0 minutes here
    # instead of 26.0, producing a strictly lower strain_score.
    assert db.update_payload["strain_score"] > compute_strain_score({3: 9.0}, sport="row")


def test_hr_zones_backfill_fills_missing_tss(monkeypatch):
    """
    build_workout_payload() never populates hr_zone_*_pct (Garmin's activity
    summary doesn't include it), so process_and_save_workout()'s HR-zone TSS
    branch can't fire on first sync — tss is left at 0.0. Once zones are known
    from the downloaded stream, this function must fill tss in rather than
    leave the workout permanently stuck at 0.
    """
    from app.services.algorithms import compute_hrss_from_zones

    monkeypatch.setattr(
        garmin_service, "compute_zone_distribution", lambda samples, zones: {"Z3": 100.0}
    )
    streams = {"heartrate": [165] * 540}
    db = _FakeZonesDB(_TEST_ATHLETE_ROW, existing_tss=0.0)

    garmin_service._update_workout_hr_zones_from_streams(
        db, "workout-1", "athlete-1", streams, duration_seconds=1560, sport="row",
    )

    expected_tss = compute_hrss_from_zones(
        zone_minutes={3: 26.0},
        max_hr=190, resting_hr=50, threshold_hr=165,
        sport="row", gender="male",
        threshold_hr_source="manual", hr_zone_method="lthr",
    )
    assert expected_tss > 0
    assert db.update_payload["tss"] == expected_tss


def test_hr_zones_backfill_does_not_clobber_existing_tss(monkeypatch):
    """A workout that already has a real (power/pace-derived) TSS must not be
    overwritten by the weaker HR-zone estimate when zones arrive later."""
    monkeypatch.setattr(
        garmin_service, "compute_zone_distribution", lambda samples, zones: {"Z3": 100.0}
    )
    streams = {"heartrate": [165] * 540}
    db = _FakeZonesDB(_TEST_ATHLETE_ROW, existing_tss=45.0)

    garmin_service._update_workout_hr_zones_from_streams(
        db, "workout-1", "athlete-1", streams, duration_seconds=1560, sport="row",
    )

    assert "tss" not in db.update_payload
    # Zones/strain still update — only tss is protected.
    assert "hr_zone_3_pct" in db.update_payload
    assert "strain_score" in db.update_payload


def test_recompute_workout_tss_for_athlete_reprocesses_zero_tss(monkeypatch):
    """
    process_and_save_workout() always writes a numeric tss (defaulting to
    0.0, never NULL), so an `is not None` guard here would skip every row
    unconditionally and never recompute anything. A workout stuck at tss=0
    must be treated as "missing" and reprocessed.
    """
    from app.services import processing

    row = {
        "id": "workout-1",
        "source": "garmin",
        "sport": "row",
        "started_at": datetime(2026, 8, 3, 21, 15, tzinfo=timezone.utc),
        "duration_seconds": 1560,
        "tss": 0.0,
    }
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[row]
    )

    calls = []

    async def fake_process_and_save_workout(payload, athlete_id, db, **kwargs):
        calls.append(payload)
        return "workout-1"

    monkeypatch.setattr(processing, "process_and_save_workout", fake_process_and_save_workout)

    updated = _run_async(processing.recompute_workout_tss_for_athlete("athlete-1", fake_db))

    assert updated == 1
    assert len(calls) == 1


# --------------------------------------------------------------------------
# _poll_interval_sec: GARMIN_SYNC_POLL_MINUTES overrides GARMIN_SYNC_POLL_HOURS
# --------------------------------------------------------------------------

def test_poll_interval_defaults_to_hours(monkeypatch):
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_HOURS", 2)
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_MINUTES", None)
    assert garmin_service._poll_interval_sec() == 2 * 3600


def test_poll_interval_minutes_overrides_hours(monkeypatch):
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_HOURS", 1)
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_MINUTES", 15)
    assert garmin_service._poll_interval_sec() == 15 * 60


def test_poll_interval_zero_minutes_falls_back_to_hours(monkeypatch):
    """0 is falsy — treated as "not overridden" rather than "poll instantly"."""
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_HOURS", 3)
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_MINUTES", 0)
    assert garmin_service._poll_interval_sec() == 3 * 3600


def test_poll_interval_negative_minutes_clamped_to_a_60s_floor(monkeypatch):
    """Guards against a misconfigured negative value turning the poll loop
    into a tight hammer against Garmin's API."""
    monkeypatch.setattr(garmin_service.settings, "GARMIN_SYNC_POLL_MINUTES", -5)
    assert garmin_service._poll_interval_sec() == 60
