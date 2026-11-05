"""
Dated history of the anchors workout TSS is scored with: FTP, threshold pace and the units that
pace is written in (table athlete_anchor_history).

A workout is scored with the values in effect on its (athlete-local) date. With no history row
for that date the athlete's profile values apply. Changing an anchor records a row from that day
and re-scores only the workouts from that day on.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

ANCHOR_FIELDS = ("ftp_watts", "threshold_pace", "measurement_units")


def load_history(db: Any, athlete_id: str) -> list[dict[str, Any]]:
    """The athlete's anchor rows, oldest first ([] if none or on error)."""
    try:
        res = (
            db.table("athlete_anchor_history")
            .select("effective_from,ftp_watts,threshold_pace,measurement_units")
            .eq("athlete_id", athlete_id)
            .order("effective_from")
            .execute()
        )
        return list(res.data or [])
    except Exception as exc:  # the profile still applies
        logger.warning("anchor history read failed athlete=%s: %s", athlete_id, exc)
        return []


def anchors_on(history: list[dict[str, Any]], day: date | str, profile: dict[str, Any]) -> dict[str, Any]:
    """FTP / threshold pace / units in effect on ``day``: the latest history row on or before
    it, else the profile."""
    d = day.isoformat() if isinstance(day, date) else str(day)[:10]
    row = None
    for h in history:
        if str(h.get("effective_from"))[:10] <= d:
            row = h
        else:
            break
    src = row if row is not None else profile
    return {k: src.get(k) for k in ANCHOR_FIELDS}


def local_day(started_at: Any, offset_min: int | None) -> date:
    """The athlete-local calendar date of a workout start (ISO string or datetime)."""
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (started_at.astimezone(timezone.utc) + timedelta(minutes=int(offset_min or 0))).date()


def record_change(db: Any, athlete_id: str, values: dict[str, Any], effective_from: date, source: str = "manual") -> None:
    """Record the anchors in effect from ``effective_from`` (one row per day; a later change the
    same day replaces it)."""
    row = {"athlete_id": athlete_id, "effective_from": effective_from.isoformat(), "source": source}
    row.update({k: values.get(k) for k in ANCHOR_FIELDS})
    db.table("athlete_anchor_history").upsert(row, on_conflict="athlete_id,effective_from").execute()


def rescore_tss(db: Any, athlete_id: str, since: date | None = None, apply: bool = True) -> list[tuple[str, float, float]]:
    """Re-score power- and pace-based workout TSS with the anchors in effect on each workout's
    date (the same branches and order as process_and_save_workout). Returns
    [(workout_id, old_tss, new_tss)] for workouts whose TSS changes; writes them when ``apply``.
    Callers rebuild the PMC afterwards."""
    from app.services.algorithms import compute_trss_pace, compute_tss_power, normalize_rowing_watts
    from app.services.processing import _fetch_all_rows, _parse_pace_to_sec_per_km, workout_ftp

    profile = (
        db.table("athletes")
        .select("ftp_watts,threshold_pace,measurement_units,timezone_offset_min")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    profile = (profile.data if profile else None) or {}
    history = load_history(db, athlete_id)
    offset = profile.get("timezone_offset_min")

    def query():
        q = (
            db.table("workouts")
            .select(
                "id,sport,started_at,duration_seconds,norm_power_w,avg_power_w,avg_pace_sec_km,tss,"
                "hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct"
            )
            .eq("athlete_id", athlete_id)
        )
        if since is not None:
            q = q.gte("started_at", (datetime.combine(since, datetime.min.time(), timezone.utc) - timedelta(days=1)).isoformat())
        return q.order("started_at")

    changes: list[tuple[str, float, float]] = []
    for r in _fetch_all_rows(query):
        day = local_day(r["started_at"], offset)
        if since is not None and day < since:
            continue
        a = anchors_on(history, day, profile)
        ftp = workout_ftp(None, a.get("ftp_watts"))
        thr = _parse_pace_to_sec_per_km(a.get("threshold_pace"), a.get("measurement_units"))
        secs = r.get("duration_seconds") or 0
        new = None
        if secs and r.get("sport") == "bike" and (r.get("norm_power_w") or 0) > 0 and ftp:
            new = compute_tss_power(secs, r["norm_power_w"], ftp)
        elif secs and r.get("sport") == "run" and (r.get("avg_pace_sec_km") or 0) > 0 and thr > 0:
            new = compute_trss_pace(duration_sec=secs, avg_pace_sec_km=float(r["avg_pace_sec_km"]), threshold_pace_sec_km=thr)
        elif (
            secs and r.get("sport") == "row" and (r.get("avg_power_w") or 0) > 0 and ftp
            and not any(r.get(f"hr_zone_{i}_pct") is not None for i in range(1, 6))
        ):
            new = compute_tss_power(secs, int(normalize_rowing_watts(r["avg_power_w"])), ftp)
        if new is None:
            continue
        new = round(float(new), 2)
        old = float(r.get("tss") or 0)
        if abs(old - new) >= 0.01:
            changes.append((r["id"], old, new))
    if apply:
        for wid, _old, new in changes:
            db.table("workouts").update({"tss": new}).eq("id", wid).execute()
    return changes


def rescore_and_rebuild(db: Any, athlete_id: str, since: date | None = None) -> int:
    """Re-score from ``since`` and rebuild the PMC and daily strain. Returns workouts changed."""
    from app.services.processing import recalculate_tss_history, refresh_all_daily_strain_sync

    changes = rescore_tss(db, athlete_id, since=since, apply=True)
    if changes:
        recalculate_tss_history(athlete_id, db)
        refresh_all_daily_strain_sync(db, athlete_id)
    return len(changes)
