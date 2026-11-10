from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import day_strain as ds
from app.services.algorithms import compute_strain_score

T0 = datetime(2026, 11, 8, 5, 0, tzinfo=timezone.utc)
ZONES = [  # an HRR-style model like the real athlete's: Z1 starts at 0 bpm
    SimpleNamespace(zone=1, min_bpm=0, max_bpm=145),
    SimpleNamespace(zone=2, min_bpm=145, max_bpm=160),
    SimpleNamespace(zone=3, min_bpm=160, max_bpm=176),
    SimpleNamespace(zone=4, min_bpm=176, max_bpm=191),
    SimpleNamespace(zone=5, min_bpm=191, max_bpm=999),
]
MAX = 200  # floor = 100 bpm


def _series(blocks):
    out, t = [], T0
    for minutes, bpm in blocks:
        for _ in range(minutes // 2):
            out.append((t, bpm))
            t += timedelta(minutes=2)
    return out


def _workout(start_min, dur_min, **zones):
    s = T0 + timedelta(minutes=start_min)
    return {"started_at": s.isoformat(), "ended_at": (s + timedelta(minutes=dur_min)).isoformat(),
            "duration_seconds": dur_min * 60, "sport": "run", **zones}


def test_resting_day_scores_nothing():
    # 24 h under the floor: without one, ~1,440 Z1 minutes would read as a hard day
    assert ds.day_strain([], _series([(1440, 70)]), ZONES, MAX)["strain"] == 0


def test_active_minutes_outside_workouts_count():
    r = ds.day_strain([], _series([(600, 70), (60, 120), (780, 70)]), ZONES, MAX)
    assert r["all_day_minutes"] == 60.0
    assert r["strain"] == compute_strain_score({1: 60.0, 2: 0, 3: 0, 4: 0, 5: 0}) > 0


def test_workout_windows_are_not_counted_twice():
    s = _series([(600, 70), (60, 150), (780, 70)])
    w = _workout(600, 60, hr_zone_2_pct=100)
    r = ds.day_strain([w], s, ZONES, MAX)
    assert r["all_day_minutes"] == 0
    assert r["strain"] == r["workouts_strain"] == compute_strain_score({1: 0, 2: 60.0, 3: 0, 4: 0, 5: 0})


def test_workouts_plus_all_day_adds_up_through_one_saturating_curve():
    s = _series([(600, 70), (60, 150), (60, 165), (720, 70)])
    w = _workout(600, 60, hr_zone_2_pct=100)
    r = ds.day_strain([w], s, ZONES, MAX)
    assert r["all_day_minutes"] == 60.0
    assert r["strain"] == compute_strain_score({1: 0, 2: 60.0, 3: 60.0, 4: 0, 5: 0})
    assert r["strain"] > r["workouts_strain"]


def test_strength_keeps_its_multiplier_and_no_max_hr_means_workouts_only():
    w = {**_workout(0, 30, hr_zone_2_pct=100), "sport": "strength"}
    zm = ds.workout_zone_minutes([w])
    assert round(zm[2], 1) == 51.0  # 30 min x 1.7
    assert ds.day_strain([w], _series([(60, 130)]), ZONES, None)["all_day_minutes"] == 0


def test_compute_day_strain_without_series_matches_the_old_workout_only_value():
    from unittest.mock import patch

    from app.services import heart_rate_series
    from app.services.processing import _compute_daily_strain_from_workout_rows

    w = _workout(0, 45, hr_zone_3_pct=60, hr_zone_4_pct=40)
    with patch.object(heart_rate_series, "load_series", return_value=None):
        assert ds.compute_day_strain(None, "a1", T0.date(), [w]) == _compute_daily_strain_from_workout_rows([w])
