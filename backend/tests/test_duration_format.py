"""Durations reach the coach as words (prod: "your average was 449 minutes", a "322 minutes"
hike, a "190 min" block). Sessions read like the plan page: minutes up to 90."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.notification_scheduler import week_numbers
from app.services.time_utils import format_duration_min, with_duration_text


import pytest


@pytest.mark.parametrize("raw, text", [
    (45, "45 min"), (60, "60 min"), (90, "90 min"), (91, "1h 31m"), (105, "1h 45m"),
    (119, "1h 59m"), (120, "2h"), (190, "3h 10m"), (322, "5h 22m"), (95.5, "1h 36m"),
])
def test_workout_durations(raw, text):
    assert format_duration_min(raw) == text


@pytest.mark.parametrize("raw, text", [
    (0.5, "0:30 min"), (0.75, "0:45 min"), (1.0, "1:00 min"), (1.5, "1:30 min"), (2.25, "2:15 min"),
])
def test_short_reps(raw, text):
    assert format_duration_min(raw) == text


@pytest.mark.parametrize("raw, text", [(45, "0h 45m"), (449, "7h 29m"), (510, "8h 30m"), (480, "8h 0m")])
def test_sleep_always_hours_and_minutes(raw, text):
    assert format_duration_min(raw, "sleep") == text


def test_bad_input():
    assert format_duration_min(None) is None


def test_tool_results_get_text_next_to_durations():
    out = with_duration_text({
        "duration_min": 90,
        "duration_seconds": 19320,  # same field in seconds: the first one wins
        "sleep_duration_min": 449,
        "structure": [{"duration_minutes": 190}],
        "time_in_zone_2_min": 45,
        "timezone_offset_min": -300,
        "pace_per_km_s": 300,
        "avg_hr": 140,
    })
    assert out["duration_text"] == "90 min"
    assert out["sleep_duration_text"] == "7h 29m"
    assert out["structure"][0]["duration_text"] == "3h 10m"
    assert out["time_in_zone_2_text"] == "45 min"
    assert "timezone_offset_text" not in out and "pace_per_km_text" not in out
    assert out["duration_min"] == 90  # raw values kept


def test_moving_time_in_seconds():
    assert with_duration_text({"moving_time_s": 19320})["moving_time_text"] == "5h 22m"


def test_weekly_summary_sends_sleep_in_hours_and_minutes():
    db = MagicMock()
    tables = {
        "tss_history": [],
        "training_plans": [],
        "biometrics": [{"sleep_duration_min": 440}, {"sleep_duration_min": 458}],
    }
    db.table.side_effect = lambda name: MagicMock(
        **{"select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value": SimpleNamespace(data=tables[name]),
           "select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value": SimpleNamespace(data=tables[name])}
    )
    nums = week_numbers(db, "a1", date(2026, 11, 1), date(2026, 11, 7))
    assert nums["avg_sleep"] == "7h 29m"
    assert "avg_sleep_min" not in nums
