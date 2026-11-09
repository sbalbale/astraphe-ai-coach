from __future__ import annotations

import re
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


def format_duration_min(minutes: Any, style: str = "workout") -> str | None:
    """A duration the way the coach should say it (the model repeated raw values such as
    "449 minutes" or "322 minutes").

    workout (sessions and blocks, like the plan page's session sheet): minutes up to 90
    ("45 min", "90 min", "1:30 min" for short reps), then "1h 45m" / "3h 10m" / "4h".
    sleep: hours and minutes from an hour up ("7h 29m"), else "45 min"."""
    try:
        total = float(minutes)
    except (TypeError, ValueError):
        return None
    if total != total or total < 0:  # NaN / negative
        return None
    # Workouts: minutes up to and including 90 ("90 min"), then "1h 45m". Sleep: from an hour.
    in_minutes = total <= 90 if style == "workout" else total < 60
    if in_minutes:
        secs = int(round(total * 60))
        m, s = divmod(secs, 60)
        return f"{m}:{s:02d} min" if s and style == "workout" else f"{int(round(total))} min"
    h, rest = divmod(int(round(total)), 60)
    return f"{h}h {rest}m" if rest else f"{h}h"


_SLEEP_HINTS = ("sleep", "bed", "nap")
_DURATION_KEY = re.compile(r"^(?P<base>.*?(?:duration|time|minutes|sleep|bed|nap)[a-z0-9_]*?)_(?P<unit>min|mins|minutes|s|sec|secs|seconds)$")
_SKIP_KEYS = re.compile(r"(^|_)(per|pace|hr|rate|offset|tz|timezone|timestamp)(_|$)")


def with_duration_text(value: Any) -> Any:
    """Tool results for the coach with a ready-to-say text next to every duration
    (duration_min: 90 -> duration_text: "90 min"; sleep_duration_min: 449 ->
    sleep_duration_text: "7h 29m"), so it never has to turn raw minutes into words."""
    if isinstance(value, list):
        return [with_duration_text(v) for v in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, v in value.items():
        out[key] = with_duration_text(v)
        if not isinstance(key, str) or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        k = key.lower()
        if k == "duration_minutes":  # plan blocks / sessions
            m = _DURATION_KEY.match("duration_min")
        else:
            m = _DURATION_KEY.match(k)
        if not m or _SKIP_KEYS.search(m.group("base")):
            continue
        minutes = float(v) / 60.0 if m.group("unit") in ("s", "sec", "secs", "seconds") else float(v)
        style = "sleep" if any(h in k for h in _SLEEP_HINTS) else "workout"
        text_key = f"{m.group('base')}_text"
        if text_key not in value and text_key not in out and (text := format_duration_min(minutes, style)):
            out[text_key] = text
    return out
