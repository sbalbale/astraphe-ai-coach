from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.services.time_utils import (
    athlete_local_date,
    athlete_local_datetime,
    fetch_athlete_timezone_offset_min,
    local_datetime_from_timezone_offset,
)


def test_local_datetime_handles_naive_input():
    naive_now = datetime(2026, 5, 26, 12, 0)  # no tzinfo
    local_now = local_datetime_from_timezone_offset(0, naive_now)
    assert local_now.tzinfo is not None


def test_fetch_athlete_timezone_offset_min_returns_zero_on_error():
    db = MagicMock()
    db.table.side_effect = RuntimeError("db down")

    assert fetch_athlete_timezone_offset_min(db, "athlete-1") == 0


def test_fetch_athlete_timezone_offset_min_reads_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"timezone_offset_min": -300}
    )

    assert fetch_athlete_timezone_offset_min(db, "athlete-1") == -300


def test_athlete_local_datetime_and_date_use_fetched_offset():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"timezone_offset_min": 60}
    )

    dt = athlete_local_datetime(db, "athlete-1")
    d = athlete_local_date(db, "athlete-1")
    assert dt.date() == d
