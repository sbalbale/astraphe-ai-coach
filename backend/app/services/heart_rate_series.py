"""
All-day heart rate: one series per athlete + local calendar day + source.

Garmin's ``dailyHeartRate`` endpoint returns the day as ``heartRateValues``, a list of
``[epoch_ms, bpm]`` pairs on a fixed 2-minute grid (720 a day; each value is the
average for those two minutes). Samples are stored as parallel arrays of seconds from
``start_at`` and bpm, so an irregular source can be stored the same way later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "heart_rate_series"

# Best source first when a day has more than one series.
SERIES_SOURCE_PRIORITY = ("garmin", "whoop", "healthkit")

# Outside this a value is a sensor artefact (Garmin uses 0 / null for off-wrist).
PLAUSIBLE_BPM = (25, 240)


@dataclass(frozen=True)
class HeartRateSeries:
    athlete_id: str
    date: date
    source: str
    samples: list[tuple[datetime, int]]  # (UTC instant, bpm), sorted
    resting_hr: int | None = None

    @property
    def start_at(self) -> datetime | None:
        return self.samples[0][0] if self.samples else None

    @property
    def end_at(self) -> datetime | None:
        return self.samples[-1][0] if self.samples else None


def _plausible(bpm: Any) -> int | None:
    try:
        v = int(round(float(bpm)))
    except (TypeError, ValueError):
        return None
    return v if PLAUSIBLE_BPM[0] <= v <= PLAUSIBLE_BPM[1] else None


def parse_garmin_heart_rate_values(heart_rates: dict[str, Any] | None) -> list[tuple[datetime, int]]:
    """``get_heart_rates`` response -> sorted (UTC instant, bpm); off-wrist / bad points dropped."""
    out: dict[datetime, int] = {}
    for point in (heart_rates or {}).get("heartRateValues") or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        bpm = _plausible(point[1])
        if bpm is None:
            continue
        try:
            ts = datetime.fromtimestamp(float(point[0]) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        out[ts] = bpm
    return sorted(out.items())


def save_series(
    db: Any,
    athlete_id: str,
    day: date,
    source: str,
    samples: list[tuple[datetime, int]],
    resting_hr: int | None = None,
) -> int:
    """
    Upsert the day's series for this source. No samples => leave any stored series
    untouched (a transient empty response must not wipe a day already synced).
    """
    if not samples:
        return 0
    samples = sorted(samples)
    start = samples[0][0]
    row = {
        "athlete_id": athlete_id,
        "date": day.isoformat(),
        "source": source,
        "start_at": start.isoformat(),
        "offsets_sec": [int(round((ts - start).total_seconds())) for ts, _ in samples],
        "bpm": [int(b) for _, b in samples],
        "resting_hr": resting_hr,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db.table(TABLE).upsert(row, on_conflict="athlete_id,date,source").execute()
    return len(samples)


def series_from_row(row: dict[str, Any]) -> HeartRateSeries | None:
    try:
        start = datetime.fromisoformat(str(row["start_at"]).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        day = date.fromisoformat(str(row["date"])[:10])
    except (KeyError, TypeError, ValueError):
        return None
    offsets = row.get("offsets_sec") or []
    bpms = row.get("bpm") or []
    samples = [
        (start + timedelta(seconds=int(o)), int(b))
        for o, b in zip(offsets, bpms)
        if o is not None and b is not None
    ]
    return HeartRateSeries(
        athlete_id=str(row.get("athlete_id")),
        date=day,
        source=str(row.get("source")),
        samples=samples,
        resting_hr=row.get("resting_hr"),
    )


def _source_rank(source: str | None) -> int:
    try:
        return SERIES_SOURCE_PRIORITY.index(source or "")
    except ValueError:
        return len(SERIES_SOURCE_PRIORITY)


def load_series(db: Any, athlete_id: str, day: date) -> HeartRateSeries | None:
    """The day's series from the best available source, or None."""
    res = (
        db.table(TABLE)
        .select("athlete_id,date,source,start_at,offsets_sec,bpm,resting_hr")
        .eq("athlete_id", athlete_id)
        .eq("date", day.isoformat())
        .execute()
    )
    rows = sorted((res.data if res else None) or [], key=lambda r: _source_rank(r.get("source")))
    for row in rows:
        series = series_from_row(row)
        if series and series.samples:
            return series
    return None


def _iso_z(value: Any) -> str | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def merge_sleep_spans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Union of sleep periods (several sources can report the same night). A merged span
    is a nap only if every period in it is.
    """
    spans = []
    for r in rows:
        s, e = _iso_z(r.get("started_at")), _iso_z(r.get("ended_at"))
        if s and e and e > s:
            spans.append([s, e, bool(r.get("is_nap"))])
    spans.sort()
    out: list[list[Any]] = []
    for s, e, nap in spans:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
            out[-1][2] = out[-1][2] and nap
        else:
            out.append([s, e, nap])
    return [{"started_at": s, "ended_at": e, "is_nap": nap} for s, e, nap in out]


_DAY_WORKOUT_COLUMNS = (
    "id, source, primary_source, sport, title, started_at, ended_at, duration_seconds, "
    "avg_hr, max_hr, strain_score, tss"
)


def build_heart_rate_day(db: Any, athlete_id: str, day: date) -> dict[str, Any]:
    """Payload for GET /v1/biometrics/heart-rate (see the route)."""
    from app.services.processing import _local_day_window_utc
    from app.services.time_utils import fetch_athlete_timezone_offset_min

    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    day_start, day_end = _local_day_window_utc(day, offset)

    series = load_series(db, athlete_id, day)
    samples = series.samples if series else []

    workouts = (
        db.table("workouts").select(_DAY_WORKOUT_COLUMNS).eq("athlete_id", athlete_id)
        .lt("started_at", day_end).gt("ended_at", day_start).order("started_at").execute()
    )
    workout_rows = (workouts.data if workouts else None) or []
    for w in workout_rows:
        w["started_at"] = _iso_z(w.get("started_at"))
        w["ended_at"] = _iso_z(w.get("ended_at"))
        w["detected"] = w.get("source") == "hr_detected"

    sleep = (
        db.table("sleep_periods").select("started_at, ended_at, is_nap").eq("athlete_id", athlete_id)
        .lt("started_at", day_end).gt("ended_at", day_start).execute()
    )
    rhr = (
        db.table("biometrics").select("date, resting_hr").eq("athlete_id", athlete_id)
        .gte("date", (day - timedelta(days=29)).isoformat()).lte("date", day.isoformat())
        .order("date").execute()
    )

    bpms = [b for _, b in samples]
    gaps = sorted((samples[i + 1][0] - samples[i][0]).total_seconds() for i in range(len(samples) - 1))
    return {
        "date": day.isoformat(),
        "day_start": _iso_z(day_start),
        "day_end": _iso_z(day_end),
        "source": series.source if series else None,
        "interval_sec": int(gaps[len(gaps) // 2]) if gaps else None,
        "resting_hr": series.resting_hr if series else None,
        "min_hr": min(bpms) if bpms else None,
        "max_hr": max(bpms) if bpms else None,
        "avg_hr": round(sum(bpms) / len(bpms)) if bpms else None,
        "samples": [{"t": _iso_z(ts), "bpm": b} for ts, b in samples],
        "workouts": workout_rows,
        "sleep": merge_sleep_spans((sleep.data if sleep else None) or []),
        "resting_hr_history": [
            {"date": r["date"], "resting_hr": r["resting_hr"]}
            for r in ((rhr.data if rhr else None) or [])
            if r.get("resting_hr")
        ],
    }
