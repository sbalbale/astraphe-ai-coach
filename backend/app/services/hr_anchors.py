"""
Fill in heart-rate anchors an athlete hasn't set, so their workouts can still be scored.

Heart-rate TSS (HRSS) needs max, resting and threshold HR. An athlete who never entered a max
HR (and whose provider doesn't send one) got TSS 0 on every workout, e.g. 92 of 92 for one
athlete. When max HR is missing it's estimated as the higher of
  - the age-based estimate (Tanaka, from date of birth), and
  - the highest heart rate recorded in the last year (a true max is at least that),
saved to the profile with max_hr_source='estimated'. A later, higher recorded HR raises an
estimated max; a value the athlete entered is never changed. Threshold HR is then estimated
from it the usual way (83% of heart-rate reserve) when that's missing too.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.algorithms import calculate_threshold_hr_est, estimate_max_hr

logger = logging.getLogger(__name__)

PLAUSIBLE_PEAK = (120, 230)

# Measured resting HR: the mean of the daily readings over this many days, once there
# are at least MIN_RHR_READINGS of them (processing.process_and_save_biometrics uses
# the same rule each time a day syncs).
RHR_WINDOW_DAYS = 42
MIN_RHR_READINGS = 3


def refresh_measured_resting_hr(db: Any, athlete_id: str, today: date | None = None) -> int | None:
    """
    Set the profile's resting HR to the measured baseline now (after the athlete
    switches back from a value they entered). Returns it, or None without enough readings
    (the profile keeps its value; the next synced day fills it in).
    """
    today = today or datetime.now(timezone.utc).date()
    from app.services.algorithms import calculate_rhr_baseline

    # Same window and baseline as the sync (process_and_save_biometrics), so switching
    # back gives the value the next synced day would set.
    res = (
        db.table("biometrics").select("date, resting_hr").eq("athlete_id", athlete_id)
        .gte("date", (today - timedelta(days=RHR_WINDOW_DAYS)).isoformat())
        .lte("date", today.isoformat()).order("date").execute()
    )
    vals = [int(r["resting_hr"]) for r in ((res.data if res else None) or []) if r.get("resting_hr")]
    if len(vals) < MIN_RHR_READINGS:
        return None
    rhr = int(round(calculate_rhr_baseline(vals)))
    db.table("athletes").update({"resting_hr": rhr, "resting_hr_source": "measured"}).eq("id", athlete_id).execute()
    return rhr


def age_on(dob: Any, today: date) -> int | None:
    try:
        d = date.fromisoformat(str(dob)[:10])
    except (TypeError, ValueError):
        return None
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return age if 10 <= age <= 100 else None


def estimated_max_hr(dob: Any, observed_peak: Any, today: date) -> int | None:
    """Higher of the age estimate and a plausible recorded peak (None if neither)."""
    candidates: list[int] = []
    age = age_on(dob, today)
    if age is not None:
        candidates.append(estimate_max_hr(age))
    try:
        peak = int(observed_peak)
        if PLAUSIBLE_PEAK[0] <= peak <= PLAUSIBLE_PEAK[1]:
            candidates.append(peak)
    except (TypeError, ValueError):
        pass
    return max(candidates) if candidates else None


def _observed_peak(db: Any, athlete_id: str, today: date) -> int | None:
    since = (datetime.combine(today, datetime.min.time(), timezone.utc) - timedelta(days=365)).isoformat()
    res = (
        db.table("workouts")
        .select("max_hr")
        .eq("athlete_id", athlete_id)
        .gte("started_at", since)
        .lte("max_hr", PLAUSIBLE_PEAK[1])
        .order("max_hr", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0].get("max_hr") if rows else None


def ensure_hr_anchors(db: Any, athlete_id: str, today: date | None = None) -> dict[str, Any]:
    """Estimate max HR (and then threshold HR) where missing; returns the profile updates made."""
    today = today or datetime.now(timezone.utc).date()
    try:
        a = (
            db.table("athletes")
            .select("max_hr,max_hr_source,threshold_hr,threshold_hr_source,resting_hr,date_of_birth")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        a = (a.data if a else None) or {}
        updates: dict[str, Any] = {}
        max_hr = a.get("max_hr")
        if not max_hr or a.get("max_hr_source") == "estimated":
            est = estimated_max_hr(a.get("date_of_birth"), _observed_peak(db, athlete_id, today), today)
            if est and (not max_hr or est > int(max_hr)):
                updates["max_hr"] = est
                updates["max_hr_source"] = "estimated"
                max_hr = est
        resting = a.get("resting_hr")
        if max_hr and resting and not a.get("threshold_hr"):
            thr = calculate_threshold_hr_est(max_hr=int(max_hr), resting_hr=int(resting))
            if thr and thr > int(resting):
                updates["threshold_hr"] = thr
                updates["threshold_hr_source"] = "estimated"
        if updates:
            db.table("athletes").update(updates).eq("id", athlete_id).execute()
            logger.info("hr anchors estimated athlete=%s %s", athlete_id, updates)
        return updates
    except Exception as exc:  # scoring falls back to what the profile has
        logger.warning("hr anchor estimate failed athlete=%s: %s", athlete_id, exc)
        return {}
