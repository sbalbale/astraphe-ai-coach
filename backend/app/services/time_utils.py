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

    workout (sessions, blocks, moving time):
      - short reps, i.e. anything with seconds or under 2 minutes: "M:SS min"
        (0.5 -> "0:30 min", 1 -> "1:00 min", 1.5 -> "1:30 min", 2.25 -> "2:15 min")
      - up to 90 minutes: "45 min", "90 min"
      - over 90: hours and minutes, "1h 31m", "3h 10m", whole hours "2h"
    sleep (sleep, time in bed, naps): always "Xh Ym" ("0h 45m", "7h 29m", "8h 0m")."""
    try:
        total = float(minutes)
    except (TypeError, ValueError):
        return None
    if total != total or total < 0:  # NaN / negative
        return None
    secs = int(round(total * 60))
    if style == "sleep":
        h, m = divmod(int(round(secs / 60)), 60)
        return f"{h}h {m}m"
    if secs > 90 * 60:
        h, rest = divmod(int(round(secs / 60)), 60)
        return f"{h}h {rest}m" if rest else f"{h}h"
    m, s = divmod(secs, 60)
    if s or m < 2:
        return f"{m}:{s:02d} min"
    return f"{m} min"


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
