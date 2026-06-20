from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_biometrics

from app.services import intervals_icu


def _run_async(coro):
    try:
        return asyncio.run(coro)
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())



def test_map_intervals_wellness_to_daily_biometrics():
    payload = {
        "id": "2026-06-18",
        "date": "2026-06-18",
        "hrv": 68.2,
        "restingHR": 47,
        "weight": 72.5,
        "sleepSecs": 7 * 60 * 60,
        "sleepScore": 91,
        "spO2": 97.5,
        "readiness": 82,
    }

    bio = intervals_icu._map_wellness_to_daily_biometrics(payload)

    assert bio.date == date(2026, 6, 18)
    assert bio.source == "intervals_icu"
    assert bio.external_id == "2026-06-18"
    assert bio.hrv_rmssd == 68.2
    assert bio.resting_hr == 47
    assert bio.weight_kg == 72.5
    assert bio.sleep_duration_min == 420
    assert bio.sleep_score == 91
    assert bio.spo2_pct == 97.5
    assert bio.readiness_score == 82


def test_map_intervals_wellness_uses_id_as_date_when_date_missing():
    bio = intervals_icu._map_wellness_to_daily_biometrics(
        {"id": "2026-06-17", "hrv": 55.0, "sleepSecs": 8 * 60 * 60}
    )

    assert bio.date == date(2026, 6, 17)
    assert bio.external_id == "2026-06-17"
    assert bio.sleep_duration_min == 480


def test_map_intervals_activity_to_workout_payload():
    payload = {
        "id": 12345,
        "name": "Morning Run",
        "type": "Run",
        "start_date": "2026-06-18T10:00:00Z",
        "elapsed_time": 3600,
        "distance": 10000.0,
        "average_heartrate": 151,
        "max_heartrate": 177,
        "trainingLoad": 74.2,
    }

    workout = intervals_icu._map_activity_to_workout_payload(payload)

    assert workout is not None
    assert workout.source == "intervals_icu"
    assert workout.external_id == "12345"
    assert workout.workout_type == "Run"
    assert workout.duration_seconds == 3600
    assert workout.distance_m == 10000.0
    assert workout.average_hr == 151
    assert workout.max_hr == 177
    assert workout.tss == 74.2
    assert workout.title == "Morning Run"


def test_fetch_intervals_wrappers_use_env_base_and_provider_paths(monkeypatch):
    calls = []

    async def fake_get_json(path, api_key, *, params=None, label=""):
        calls.append((path, api_key, params, label))
        if path.endswith("/wellness"):
            return [{"date": "2026-06-18", "hrv": 60}]
        return [{"id": "a1", "type": "Ride", "start_date": "2026-06-18T12:00:00Z"}]

    monkeypatch.setattr(intervals_icu, "_get_json", fake_get_json)

    async def _run():
        bios = await intervals_icu.fetch_biometrics(
            "i123",
            "secret",
            date(2026, 6, 18),
            date(2026, 6, 19),
        )
        workouts = await intervals_icu.fetch_workouts(
            "i123",
            "secret",
            date(2026, 6, 18),
            date(2026, 6, 19),
        )
        return bios, workouts
    bios, workouts = _run_async(_run())

    assert len(bios) == 1
    assert len(workouts) == 1
    assert calls[0][0] == "/v1/athlete/i123/wellness"
    assert calls[0][2] == {"oldest": "2026-06-18", "newest": "2026-06-19"}
    assert calls[1][0] == "/v1/athlete/i123/activities"


def test_normalize_streams_payload_preserves_all_stream_arrays():
    streams = intervals_icu._normalize_streams_payload(
        {
            "streams": {
                "time": {"data": [0, 1, 2]},
                "heartrate": [120, 121, 122],
                "latlng": {"data": [[40.0, -70.0], [40.1, -70.1]]},
                "ignored_metadata": {"units": "bpm"},
            }
        }
    )

    assert streams == {
        "time": [0, 1, 2],
        "heartrate": [120, 121, 122],
        "latlng": [[40.0, -70.0], [40.1, -70.1]],
    }


def test_normalize_streams_payload_handles_intervals_stream_object_list():
    streams = intervals_icu._normalize_streams_payload(
        [
            {"type": "time", "name": None, "data": [0, 1]},
            {"type": "heartrate", "name": None, "data": [120, 121]},
            {"type": "latlng", "name": None, "data": [40.0, 40.1], "data2": [-70.0, -70.1]},
        ]
    )

    assert streams == {
        "time": [0, 1],
        "heartrate": [120, 121],
        "latlng": [[40.0, -70.0], [40.1, -70.1]],
    }


def test_fetch_activity_streams_treats_strava_proxy_422_as_unavailable(monkeypatch):
    async def fake_get_json(*_args, **_kwargs):
        raise intervals_icu.HTTPException(status_code=422, detail="Cannot read Strava activities via the API")

    monkeypatch.setattr(intervals_icu, "_get_json", fake_get_json)

    assert _run_async(intervals_icu.fetch_activity_streams("i123", "secret")) == {}


def test_save_activity_summary_fetches_and_stores_streams(monkeypatch):
    calls = {}

    async def fake_process(workout, athlete_id, db, **kwargs):
        calls["workout"] = workout
        calls["athlete_id"] = athlete_id
        calls["process_kwargs"] = kwargs
        return "workout-1"

    async def fake_fetch_streams(activity_id, api_key):
        calls["activity_id"] = activity_id
        calls["api_key"] = api_key
        return {"heartrate": [120, 121], "latlng": [[1.0, 2.0]]}

    def fake_upsert(db, workout_id, athlete_id, time_series):
        calls["stream_upsert"] = (workout_id, athlete_id, time_series)
        return True

    def fake_update_zones(db, workout_id, athlete_id, streams):
        calls["zone_update"] = (workout_id, athlete_id, streams["heartrate"])
        return True

    monkeypatch.setattr(intervals_icu, "process_and_save_workout", fake_process)
    monkeypatch.setattr(intervals_icu, "fetch_activity_streams", fake_fetch_streams)
    monkeypatch.setattr(intervals_icu, "_upsert_activity_streams", fake_upsert)
    monkeypatch.setattr(intervals_icu, "_update_workout_hr_zones_from_streams", fake_update_zones)
    saved = _run_async(
        intervals_icu._save_activity_summary_and_streams(
            {
                "id": "i55751783",
                "type": "Ride",
                "start_date_local": "2026-06-18T12:00:00",
                "moving_time": 1800,
                "icu_training_load": 42,
            },
            "athlete-1",
            "secret",
            object(),
        )
    )

    assert saved == (True, True)
    assert calls["activity_id"] == "i55751783"
    assert calls["stream_upsert"] == (
        "workout-1",
        "athlete-1",
        {"heartrate": [120, 121], "latlng": [[1.0, 2.0]]},
    )
    assert calls["zone_update"] == ("workout-1", "athlete-1", [120, 121])
    assert calls["workout"].tss == 42


class _RecordingQuery:
    def __init__(self, db, table_name):
        self.db = db
        self.table_name = table_name
        self.single_mode = False
        self.payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def lt(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single_mode = True
        return self

    def single(self):
        self.single_mode = True
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def upsert(self, payload, *_args, **_kwargs):
        self.payload = payload
        self.db.upserts.setdefault(self.table_name, []).append(payload)
        return self

    def execute(self):
        if self.table_name == "athletes" and self.single_mode:
            return SimpleNamespace(data={"id": "athlete-1", "max_hr": 190})
        return SimpleNamespace(data=None if self.single_mode else [])


class _RecordingDb:
    def __init__(self):
        self.upserts = {}

    def table(self, table_name):
        return _RecordingQuery(self, table_name)


def test_process_biometrics_preserves_intervals_daily_sleep_without_session_times():
    db = _RecordingDb()
    process_and_save_biometrics(
        DailyBiometrics(
            date=date(2026, 6, 17),
            source="intervals_icu",
            external_id="2026-06-17",
            hrv_rmssd=62.0,
            resting_hr=48,
            sleep_duration_min=450,
            sleep_in_bed_min=480,
            sleep_deep_pct=20.0,
            sleep_rem_pct=25.0,
            sleep_light_pct=50.0,
            sleep_awake_pct=5.0,
        ),
        "athlete-1",
        db,
        skip_pmc_recalc=True,
    )

    saved = db.upserts["biometrics"][0]
    assert saved["date"] == "2026-06-17"
    assert saved["sleep_duration_min"] == 450
    assert saved["sleep_in_bed_min"] == 480
    assert saved["sleep_deep_pct"] == 20.0
    assert saved["sleep_rem_pct"] == 25.0
    assert saved["hrv_source"] == "intervals_icu"
