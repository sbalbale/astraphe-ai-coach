from __future__ import annotations

import asyncio
from datetime import date

from app.services import intervals_icu


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

    bios, workouts = asyncio.run(_run())

    assert len(bios) == 1
    assert len(workouts) == 1
    assert calls[0][0] == "/v1/athlete/i123/wellness"
    assert calls[0][2] == {"oldest": "2026-06-18", "newest": "2026-06-19"}
    assert calls[1][0] == "/v1/athlete/i123/activities"
