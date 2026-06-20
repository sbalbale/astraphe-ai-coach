from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from app.models.biometrics import DailyBiometrics
from app.services.processing import _choose_biometric_metric, _compute_sleep_score_without_architecture, process_and_save_biometrics

from app.services import intervals_icu
from app.routers import sync as sync_router


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

def test_map_intervals_wellness_derives_sleep_stage_percentages_from_seconds():
    bio = intervals_icu._map_wellness_to_daily_biometrics(
        {
            "id": "2026-06-17",
            "sleepSecs": 8 * 60 * 60,
            "deepSleepSecs": 90 * 60,
            "remSleepSecs": 120 * 60,
            "lightSleepSecs": 270 * 60,
        }
    )

    assert bio.sleep_deep_pct == 18.8
    assert bio.sleep_rem_pct == 25.0
    assert bio.sleep_light_pct == 56.2



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

    def fake_update_anchors(db, athlete_id, activity):
        calls["anchor_update"] = (athlete_id, activity["icu_resting_hr"], activity["athlete_max_hr"], activity["lthr"])
        return {"resting_hr": 52, "max_hr": 198, "threshold_hr": 172}


    monkeypatch.setattr(intervals_icu, "process_and_save_workout", fake_process)
    monkeypatch.setattr(intervals_icu, "fetch_activity_streams", fake_fetch_streams)
    monkeypatch.setattr(intervals_icu, "_upsert_activity_streams", fake_upsert)
    monkeypatch.setattr(intervals_icu, "_update_workout_hr_zones_from_streams", fake_update_zones)
    monkeypatch.setattr(intervals_icu, "_update_athlete_hr_anchors_from_activity", fake_update_anchors)
    saved = _run_async(
        intervals_icu._save_activity_summary_and_streams(
            {
                "id": "i55751783",
                "type": "Ride",
                "start_date_local": "2026-06-18T12:00:00",
                "moving_time": 1800,
                "icu_training_load": 42,
                "icu_resting_hr": 52,
                "athlete_max_hr": 198,
                "lthr": 172,
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
    assert calls["anchor_update"] == ("athlete-1", 52, 198, 172)



class _ZoneQuery:
    def __init__(self, db, table_name):
        self.db = db
        self.table_name = table_name
        self.single_mode = False
        self.payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single_mode = True
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.table_name == "athletes":
            return SimpleNamespace(
                data={
                    "id": "athlete-1",
                    "max_hr": 190,
                    "resting_hr": 50,
                    "threshold_hr": 170,
                    "threshold_hr_source": "manual",
                    "hr_zone_method": "lthr",
                }
            )
        if self.table_name == "workouts" and self.payload is not None:
            self.db.workout_updates.append(self.payload)
            return SimpleNamespace(data=[self.payload])
        return SimpleNamespace(data=None if self.single_mode else [])


class _ZoneDb:
    def __init__(self):
        self.workout_updates = []

    def table(self, table_name):
        return _ZoneQuery(self, table_name)


def test_update_workout_hr_zones_from_intervals_streams():
    db = _ZoneDb()

    updated = intervals_icu._update_workout_hr_zones_from_streams(
        db,
        "workout-1",
        "athlete-1",
        {"heartrate": [120, 145, 155, 165, 185] * 60},
    )

    assert updated is True
    update = db.workout_updates[0]
    assert update["avg_hr"] == 154
    assert update["max_hr"] == 185
    assert update["hr_zone_1_pct"] == 20
    assert update["hr_zone_2_pct"] == 20
    assert update["hr_zone_3_pct"] == 20
    assert update["hr_zone_4_pct"] == 20
    assert update["hr_zone_5_pct"] == 20
    assert update["strain_score"] > 0


def test_update_athlete_hr_anchors_from_intervals_activity():
    db = _ZoneDb()

    update = intervals_icu._update_athlete_hr_anchors_from_activity(
        db,
        "athlete-1",
        {"icu_resting_hr": 61, "athlete_max_hr": 204, "lthr": 185},
    )

    assert update == {
        "max_hr": 204,
        "resting_hr": 61,
        "threshold_hr": 185,
        "threshold_hr_source": "estimated",
    }


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


def test_process_biometrics_uses_duration_backup_when_intervals_stages_missing():
    db = _RecordingDb()
    process_and_save_biometrics(
        DailyBiometrics(
            date=date(2026, 6, 13),
            source="intervals_icu",
            external_id="2026-06-13",
            hrv_rmssd=43.29,
            resting_hr=61,
            sleep_duration_min=454,
            sleep_score=12,
        ),
        "athlete-1",
        db,
        skip_pmc_recalc=True,
    )

    saved = db.upserts["biometrics"][0]
    assert saved["sleep_duration_min"] == 454
    assert saved["sleep_deep_pct"] is None
    assert saved["sleep_rem_pct"] is None
    assert saved["sleep_score"] == 94


def test_duration_backup_sleep_score_has_no_oversleep_penalty():
    assert _compute_sleep_score_without_architecture(480, 480) == 100
    assert _compute_sleep_score_without_architecture(540, 480) == 100
    assert _compute_sleep_score_without_architecture(600, 480) == 100


def test_biometric_quality_merge_keeps_whoop_sleep_stages_over_intervals():
    existing = {
        "sleep_deep_pct": 18.0,
        "sleep_rem_pct": 24.0,
        "metric_sources": {},
        "hrv_source": "whoop",
    }
    metric_sources = {"sleep_deep_pct": "whoop", "sleep_rem_pct": "whoop"}

    deep, deep_source = _choose_biometric_metric(
        existing,
        metric_sources,
        "sleep_deep_pct",
        None,
        "intervals_icu",
    )
    rem, rem_source = _choose_biometric_metric(
        existing,
        metric_sources,
        "sleep_rem_pct",
        0.0,
        "intervals_icu",
    )

    assert deep == 18.0
    assert deep_source == "whoop"
    assert rem == 24.0
    assert rem_source == "whoop"


def test_biometric_quality_merge_allows_manual_weight_over_intervals():
    existing = {"weight_kg": 80.0, "metric_sources": {"weight_kg": "intervals_icu"}}

    weight, source = _choose_biometric_metric(
        existing,
        existing["metric_sources"],
        "weight_kg",
        78.5,
        "manual",
    )

    assert weight == 78.5
    assert source == "manual"


class _IntervalsBackfillQuery:
    def __init__(self, row):
        self.row = row

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.row)


class _IntervalsBackfillDb:
    def __init__(self, row):
        self.row = row

    def table(self, table_name):
        assert table_name == "oauth_tokens"
        return _IntervalsBackfillQuery(self.row)


def test_intervals_backfill_route_schedules_authenticated_athlete(monkeypatch):
    calls = {}

    async def fake_backfill(athlete_id, intervals_athlete_id, api_key, db, days):
        calls["backfill"] = (athlete_id, intervals_athlete_id, api_key, db, days)
        return {"workouts": 1, "streams": 1, "biometrics": 1, "days": days}

    class _FakeTask:
        def __init__(self, coro):
            self.coro = coro

    def fake_create_task(coro):
        calls["task"] = _FakeTask(coro)
        return calls["task"]

    monkeypatch.setattr(sync_router.intervals_icu_service, "backfill_historical_data", fake_backfill)
    monkeypatch.setattr(sync_router.asyncio, "create_task", fake_create_task)
    db = _IntervalsBackfillDb({"access_token": "secret", "external_user_id": "i123"})

    result = _run_async(sync_router.intervals_icu_backfill_now(days=999, athlete_id="athlete-1", admin_db=db))
    _run_async(calls["task"].coro)

    assert result == {"status": "success", "scheduled": True, "days": 365}
    assert calls["backfill"] == ("athlete-1", "i123", "secret", db, 365)
