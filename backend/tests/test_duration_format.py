"""Durations reach the coach as hours and minutes (prod: "your average was 449 minutes")."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.notification_scheduler import week_numbers
from app.services.time_utils import format_duration_min


def test_format_duration_min():
    assert format_duration_min(45) == "45 min"
    assert format_duration_min(60) == "1h"
    assert format_duration_min(449) == "7h 29m"
    assert format_duration_min(322.4) == "5h 22m"
    assert format_duration_min(None) is None


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
