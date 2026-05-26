from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


MIN_TIMEZONE_OFFSET_MIN = -14 * 60
MAX_TIMEZONE_OFFSET_MIN = 14 * 60


def coerce_timezone_offset_min(value: Any) -> int:
    """Return a sane fixed UTC offset in minutes."""
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return 0
    return max(MIN_TIMEZONE_OFFSET_MIN, min(MAX_TIMEZONE_OFFSET_MIN, offset))


def local_datetime_from_timezone_offset(
    offset_min: Any,
    now_utc: datetime | None = None,
) -> datetime:
    """
    Convert a UTC instant to the athlete's fixed-offset local datetime.

    `timezone_offset_min` follows the app convention: local time = UTC + offset.
    Example: US Eastern daylight time is -240.
    """
    offset = coerce_timezone_offset_min(offset_min)
    tz = timezone(timedelta(minutes=offset))
    utc_now = now_utc or datetime.now(timezone.utc)
    if utc_now.tzinfo is None:
        utc_now = utc_now.replace(tzinfo=timezone.utc)
    return utc_now.astimezone(tz)


def local_date_from_timezone_offset(
    offset_min: Any,
    now_utc: datetime | None = None,
) -> date:
    return local_datetime_from_timezone_offset(offset_min, now_utc).date()


def fetch_athlete_timezone_offset_min(db: Any, athlete_id: str) -> int:
    try:
        res = (
            db.table("athletes")
            .select("timezone_offset_min")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = res.data or {}
        return coerce_timezone_offset_min(row.get("timezone_offset_min"))
    except Exception:
        return 0


def athlete_local_datetime(db: Any, athlete_id: str) -> datetime:
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    return local_datetime_from_timezone_offset(offset)


def athlete_local_date(db: Any, athlete_id: str) -> date:
    return athlete_local_datetime(db, athlete_id).date()
