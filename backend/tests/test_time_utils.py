from __future__ import annotations

from datetime import datetime, timezone

from app.services.time_utils import (
    coerce_timezone_offset_min,
    local_date_from_timezone_offset,
    local_datetime_from_timezone_offset,
)


def test_local_date_uses_negative_timezone_offset_before_midnight_utc():
    utc_now = datetime(2026, 5, 26, 0, 30, tzinfo=timezone.utc)

    assert local_date_from_timezone_offset(-240, utc_now).isoformat() == "2026-05-25"


def test_local_datetime_preserves_fixed_offset():
    utc_now = datetime(2026, 5, 26, 0, 30, tzinfo=timezone.utc)

    local_now = local_datetime_from_timezone_offset(-240, utc_now)

    assert local_now.isoformat(timespec="minutes") == "2026-05-25T20:30-04:00"


def test_timezone_offset_is_clamped_to_sane_bounds():
    assert coerce_timezone_offset_min(-9999) == -840
    assert coerce_timezone_offset_min(9999) == 840
    assert coerce_timezone_offset_min("not-an-int") == 0
