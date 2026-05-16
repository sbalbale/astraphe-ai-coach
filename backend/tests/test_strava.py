"""Tests for Strava helpers (rowing intervals, stream-derived splits)."""
from __future__ import annotations

from app.services.strava import (
    _pick_best_laps,
    compute_500m_splits_from_streams,
    get_rowing_intervals,
)


def test_compute_500m_splits_empty_streams():
    assert compute_500m_splits_from_streams({}) == []


def test_compute_500m_splits_missing_distance_or_time():
    assert compute_500m_splits_from_streams({"time": {"data": [0, 1]}}) == []
    assert compute_500m_splits_from_streams({"distance": {"data": [0, 100]}}) == []


def test_compute_500m_splits_single_500m_piece():
    # Linear 500m in 100s at 1 Hz: 5 m/s average → pace 100s/500m
    dist = [float(i * 5) for i in range(101)]  # 0..500
    time_s = list(range(101))
    streams = {
        "distance": {"data": dist},
        "time": {"data": time_s},
        "heartrate": {"data": [150] * 101},
    }
    splits = compute_500m_splits_from_streams(streams)
    assert len(splits) == 1
    assert splits[0]["split_number"] == 1
    assert splits[0]["distance"] == 500.0
    assert splits[0]["elapsed_time"] == 100
    assert splits[0]["pace_per_500m"] == 100
    assert splits[0]["average_heartrate"] == 150.0
    assert splits[0]["source"] == "stream_derived"
    assert splits[0]["start_index"] == 0
    assert splits[0]["end_index"] == 100


def test_get_rowing_intervals_prefers_laps():
    # 5 × ~500m work laps; avg_speed 2.5 m/s → 200 s/500m (under 210s threshold)
    laps = [
        {
            "distance": 500.0,
            "elapsed_time": 120,
            "moving_time": 120,
            "average_speed": 2.5,
            "average_heartrate": 160,
            "max_heartrate": 170,
            "start_index": 0,
            "end_index": 99,
        }
        for _ in range(5)
    ]
    activity = {"laps": laps}
    streams = {"distance": {"data": [0, 500]}, "time": {"data": [0, 120]}}
    intervals, source = get_rowing_intervals(activity, streams)
    assert source == "laps"
    assert len(intervals) == 5
    assert all(i["source"] == "laps" for i in intervals)
    assert intervals[0]["pace_per_500m"] == 200
    assert intervals[0]["split_number"] == 1


def test_get_rowing_intervals_stream_fallback_no_laps():
    dist = [float(i * 5) for i in range(101)]
    time_s = list(range(101))
    streams = {"distance": {"data": dist}, "time": {"data": time_s}}
    intervals, source = get_rowing_intervals({"laps": []}, streams)
    assert source == "stream_derived"
    assert len(intervals) == 1
    assert intervals[0]["source"] == "stream_derived"


def test_pick_best_laps_prefers_embedded_over_synthetic_api_lap():
    api_laps = [{"distance": 0, "elapsed_time": 3599, "average_speed": 0}]
    embedded = [
        {"distance": 500.0, "elapsed_time": 120, "average_speed": 2.0},
        {"distance": 500.0, "elapsed_time": 130, "average_speed": 1.9},
    ]
    picked = _pick_best_laps(api_laps, embedded)
    assert len(picked) == 2
    assert picked[0]["distance"] == 500.0


def test_get_rowing_intervals_uses_all_device_laps():
    # 2k pieces are kept as-is (no filtering to 500m-only)
    laps = [
        {
            "distance": 2000.0,
            "elapsed_time": 480,
            "average_speed": 2.5,
        }
        for _ in range(4)
    ]
    dist = [float(i * 5) for i in range(101)]
    time_s = list(range(101))
    streams = {"distance": {"data": dist}, "time": {"data": time_s}}
    intervals, source = get_rowing_intervals({"laps": laps}, streams)
    assert source == "laps"
    assert len(intervals) == 4
    assert intervals[0]["pace_per_500m"] == 200
