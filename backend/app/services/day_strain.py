"""
Day strain: the day's cardiovascular load, workouts plus everything else.

Strain used to come only from workouts' heart-rate zones, so a day of walking, stairs
or a physical job scored 0 for anyone without a wearable that reports its own day
strain. With the all-day heart rate series (heart_rate_series), the minutes outside
workouts count too:

    zone_minutes = workouts' zone minutes (as before; strength x NEUROMUSCULAR_MULTIPLIER)
                 + all-day minutes at or above REST_FLOOR_FRACTION of max HR, outside
                   every workout window, by the athlete's zones
    strain = compute_strain_score(zone_minutes)          # same 0-100 saturating scale

The floor matters: every zone model starts Z1 at 0 bpm with a 0.5 coefficient, so a
day of resting heart rate (~1,400 Z1 minutes) would otherwise score near 100. Half of
max HR is the usual bottom of the easiest training zone and the same "counts as rest"
line the Heart rate screen uses. On 40 days of real data it added +3 to +10 to typical
training days, 0-3 to rest days, and +24 to a 200-active-minute day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.algorithms import NEUROMUSCULAR_MULTIPLIER, compute_strain_score

REST_FLOOR_FRACTION = 0.5


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _workout_seconds(row: dict[str, Any]) -> float:
    # Same resolution as GET /v1/workouts (explicit duration fields, then end - start).
    from app.services.processing import _workout_duration_seconds_from_row

    return float(_workout_duration_seconds_from_row(row))


def workout_zone_minutes(rows: list[dict[str, Any]]) -> dict[int, float]:
    """Zone minutes from workouts' stored zone percentages (strength weighted up)."""
    out = {z: 0.0 for z in range(1, 6)}
    for w in rows:
        dur_min = _workout_seconds(w) / 60.0
        if not dur_min:
            continue
        scale = NEUROMUSCULAR_MULTIPLIER if w.get("sport") == "strength" else 1.0
        for z in range(1, 6):
            out[z] += (float(w.get(f"hr_zone_{z}_pct") or 0) / 100.0) * dur_min * scale
    return out


def _workout_spans(rows: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    spans = []
    for w in rows:
        s = _parse_ts(w.get("started_at"))
        if s is None:
            continue
        e = _parse_ts(w.get("ended_at")) or s + timedelta(seconds=_workout_seconds(w))
        if e > s:
            spans.append((s, e))
    return spans


def all_day_zone_minutes(
    samples: list[tuple[datetime, int]],
    workout_rows: list[dict[str, Any]],
    zones: list[Any],
    max_hr: int | None,
) -> dict[int, float]:
    """
    Zone minutes of the all-day series outside workouts, at or above the rest floor.
    ``zones``: HRZone-like objects (zone, min_bpm, max_bpm). Pure.
    """
    out = {z: 0.0 for z in range(1, 6)}
    if not samples or not max_hr or not zones:
        return out
    from app.services.hr_activity_detection import _sample_weights

    floor = REST_FLOOR_FRACTION * float(max_hr)
    spans = _workout_spans(workout_rows)
    ordered = sorted(zones, key=lambda z: z.min_bpm)
    for (ts, bpm), sec in zip(samples, _sample_weights(samples)):
        if bpm < floor or any(s <= ts < e for s, e in spans):
            continue
        zone = ordered[0].zone
        for z in ordered:
            if bpm >= z.min_bpm:
                zone = z.zone
        if 1 <= zone <= 5:
            out[zone] += sec / 60.0
    return out


def day_strain(
    workout_rows: list[dict[str, Any]],
    samples: list[tuple[datetime, int]],
    zones: list[Any],
    max_hr: int | None,
) -> dict[str, Any]:
    """Pure: the day's strain plus its parts (for the API / UI)."""
    wz = workout_zone_minutes(workout_rows)
    az = all_day_zone_minutes(samples, workout_rows, zones, max_hr)
    total = {z: wz[z] + az[z] for z in range(1, 6)}
    return {
        "strain": compute_strain_score(total),
        "workouts_strain": compute_strain_score(wz),
        "all_day_minutes": round(sum(az.values()), 1),
    }


def compute_day_strain(db: Any, athlete_id: str, day: date, workout_rows: list[dict[str, Any]]) -> int:
    """The athlete's strain for their local ``day`` (workout rows already fetched)."""
    from app.services.heart_rate_series import drop_flatlines, load_series
    from app.services.hr_anchors import estimated_max_hr
    from app.services.hr_zones import get_athlete_zones

    series = load_series(db, athlete_id, day)
    if series is None or not series.samples:
        return compute_strain_score(workout_zone_minutes(workout_rows))
    res = db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute()
    athlete = (res.data if res else None) or {}
    max_hr = athlete.get("max_hr") or estimated_max_hr(athlete.get("date_of_birth"), None, day)
    # Garmin's carried-forward values (no sensor signal) aren't activity.
    samples = drop_flatlines(series.samples)
    return day_strain(workout_rows, samples, get_athlete_zones(athlete), max_hr)["strain"]
