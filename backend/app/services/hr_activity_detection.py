"""
Detect workouts from all-day heart rate, the way WHOOP auto-detects activities.

Input is a day's ``heart_rate_series`` (Garmin: 2-minute averages). A session is a
stretch of heart rate at or above ``ENTER_HRR`` of heart-rate reserve totalling at
least ``MIN_ACTIVE_SEC``. Cool spells of up to ``MERGE_GAP_SEC`` inside it (interval
rests, a traffic light) don't split it; one warm-up sample at or above ``STAY_HRR``
just before it is included.

Detections are saved as workouts with source ``hr_detected``, last in
``SOURCE_PRIORITY``: any recorded workout wins. Concretely:
  - a window overlapping an existing recorded workout is never saved;
  - a recorded workout that arrives later replaces overlapping detections
    (``processing._find_or_create_canonical_workout_sync`` deletes them);
  - a detection the athlete deletes is remembered in ``hr_detection_dismissals`` and
    not detected again; one the athlete edits becomes a manual workout.

Because the input is 2-minute averages, boundaries are only good to ~2 minutes and
the recorded max HR is the highest 2-minute average, not the true peak.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.heart_rate_series import HeartRateSeries, load_series

logger = logging.getLogger(__name__)

SOURCE = "hr_detected"
TITLE = "Detected activity"

# Fractions of heart-rate reserve: (bpm - resting) / (max - resting).
ENTER_HRR = 0.40
STAY_HRR = 0.30
MIN_ACTIVE_SEC = 10 * 60
MIN_WINDOW_SEC = 10 * 60
# Cool spells up to this long inside a session are part of it.
MERGE_GAP_SEC = 6 * 60
# A hole in the series longer than this (watch off) ends a session.
MAX_SAMPLE_GAP_SEC = 5 * 60
# A detection this close to a recorded workout is the same effort (warm-up, cool-down).
RECORDED_PAD_SEC = 5 * 60
DEFAULT_SAMPLE_SEC = 120
# Anchors closer together than this can't separate rest from effort.
MIN_RESERVE_BPM = 30


@dataclass(frozen=True)
class DetectedWindow:
    start: datetime
    end: datetime
    samples: list[tuple[datetime, int]]
    weights: list[float]

    @property
    def duration_sec(self) -> int:
        return int(round((self.end - self.start).total_seconds()))

    @property
    def avg_hr(self) -> int:
        total = sum(self.weights) or 1.0
        return int(round(sum(b * w for (_, b), w in zip(self.samples, self.weights)) / total))

    @property
    def max_hr(self) -> int:
        return max(b for _, b in self.samples)


def _sample_weights(samples: list[tuple[datetime, int]]) -> list[float]:
    """Seconds each sample stands for: time to the next one, capped at a hole."""
    if not samples:
        return []
    diffs = [(samples[i + 1][0] - samples[i][0]).total_seconds() for i in range(len(samples) - 1)]
    usual = statistics.median([d for d in diffs if d > 0]) if any(d > 0 for d in diffs) else DEFAULT_SAMPLE_SEC
    usual = min(usual, MAX_SAMPLE_GAP_SEC)
    weights = [d if 0 < d <= MAX_SAMPLE_GAP_SEC else usual for d in diffs]
    weights.append(usual)
    return weights


def detect_windows(
    samples: list[tuple[datetime, int]], resting_hr: int | None, max_hr: int | None
) -> list[DetectedWindow]:
    """Sessions in a sorted (instant, bpm) series. Pure: no I/O."""
    if not samples or not resting_hr or not max_hr or int(max_hr) - int(resting_hr) < MIN_RESERVE_BPM:
        return []
    rest, reserve = int(resting_hr), int(max_hr) - int(resting_hr)
    enter_bpm = rest + ENTER_HRR * reserve
    stay_bpm = rest + STAY_HRR * reserve
    weights = _sample_weights(samples)

    def contiguous(i: int) -> bool:  # sample i follows i-1 without a hole
        return (samples[i][0] - samples[i - 1][0]).total_seconds() <= MAX_SAMPLE_GAP_SEC

    # 1. Runs of consecutive samples at or above the enter threshold. (Not the stay
    # threshold: many people's everyday standing / walking heart rate sits around it, and
    # sessions built from it ran on for most of an hour after the workout ended.)
    runs: list[list[int]] = []
    for i, (_, bpm) in enumerate(samples):
        if bpm < enter_bpm:
            continue
        if runs and runs[-1][1] == i - 1 and contiguous(i):
            runs[-1][1] = i
        else:
            runs.append([i, i])

    # 2. Merge runs split by a short cool spell (with no hole in between).
    merged: list[list[int]] = []
    for run in runs:
        if merged:
            prev = merged[-1]
            gap = (samples[run[0]][0] - samples[prev[1]][0]).total_seconds()
            if gap <= MERGE_GAP_SEC and all(contiguous(k) for k in range(prev[1] + 1, run[0] + 1)):
                prev[1] = run[1]
                continue
        merged.append(list(run))

    # 3. Keep sessions long and hard enough; a warm-up sample just before the first hard
    # one (at or above the stay threshold) belongs to the session.
    out: list[DetectedWindow] = []
    for i0, i1 in merged:
        if i0 > 0 and samples[i0 - 1][1] >= stay_bpm and contiguous(i0):
            i0 -= 1
        seg = samples[i0 : i1 + 1]
        w = weights[i0 : i1 + 1]
        active = sum(wt for (_, b), wt in zip(seg, w) if b >= enter_bpm)
        start = seg[0][0]
        end = seg[-1][0] + timedelta(seconds=w[-1])
        if (end - start).total_seconds() >= MIN_WINDOW_SEC and active >= MIN_ACTIVE_SEC:
            out.append(DetectedWindow(start=start, end=end, samples=seg, weights=w))
    return out


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime, pad_sec: float = 0) -> bool:
    pad = timedelta(seconds=pad_sec)
    return a0 < b1 + pad and b0 < a1 + pad


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def external_id_for(athlete_id: str, start: datetime) -> str:
    # workouts' unique key is (source, external_id) across all athletes.
    return f"{athlete_id}:{int(start.timestamp())}"


def _zone_pcts(window: DetectedWindow, athlete: dict[str, Any]) -> dict[str, int]:
    from app.services.hr_zones import compute_zone_distribution, get_athlete_zones

    # The series is evenly spaced (Garmin: 2 min), so equal sample weights are right.
    dist = compute_zone_distribution([b for _, b in window.samples], get_athlete_zones(athlete))
    return {f"hr_zone_{z}_pct": int(round(dist.get(f"Z{z}", 0.0))) for z in range(1, 6)}


def _anchors(series: HeartRateSeries, athlete: dict[str, Any], day: date) -> tuple[int | None, int | None]:
    from app.services.hr_anchors import estimated_max_hr

    resting = series.resting_hr or athlete.get("resting_hr")
    max_hr = athlete.get("max_hr") or estimated_max_hr(athlete.get("date_of_birth"), None, day)
    return (int(resting) if resting else None, int(max_hr) if max_hr else None)


async def detect_and_save_for_day(db: Any, athlete_id: str, day: date) -> dict[str, int]:
    """
    (Re)detect the day's sessions and sync them to ``workouts``. Idempotent: an hourly
    re-run updates the same rows (keyed by start), and removes detections the latest
    series no longer supports. Leaves TSS history to the caller; refreshes the day's strain.
    """
    import asyncio

    from app.models.workout import WorkoutPayload
    from app.services.processing import _refresh_daily_strain_for_day_sync, process_and_save_workout

    result = {"saved": 0, "removed": 0}
    series = await asyncio.to_thread(load_series, db, athlete_id, day)
    if series is None or not series.samples:
        return result

    def _fetch_context():
        athlete = (
            db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute()
        )
        span_start = series.start_at - timedelta(seconds=RECORDED_PAD_SEC)
        span_end = series.end_at + timedelta(seconds=DEFAULT_SAMPLE_SEC + RECORDED_PAD_SEC)
        workouts = (
            db.table("workouts")
            .select("id,source,external_id,started_at,ended_at,duration_seconds,avg_hr,max_hr")
            .eq("athlete_id", athlete_id)
            .lt("started_at", span_end.isoformat())
            .gte("started_at", (span_start - timedelta(hours=24)).isoformat())
            .execute()
        )
        dismissals = (
            db.table("hr_detection_dismissals")
            .select("started_at,ended_at")
            .eq("athlete_id", athlete_id)
            .lt("started_at", span_end.isoformat())
            .gt("ended_at", span_start.isoformat())
            .execute()
        )
        return (
            (athlete.data if athlete else None) or {},
            (workouts.data if workouts else None) or [],
            (dismissals.data if dismissals else None) or [],
        )

    athlete, workout_rows, dismissal_rows = await asyncio.to_thread(_fetch_context)
    resting, max_hr = _anchors(series, athlete, day)
    windows = detect_windows(series.samples, resting, max_hr)

    def _span(row: dict[str, Any]) -> tuple[datetime, datetime] | None:
        s = _parse_ts(row.get("started_at"))
        if s is None:
            return None
        e = _parse_ts(row.get("ended_at")) or s + timedelta(seconds=int(row.get("duration_seconds") or 0))
        return s, e

    recorded = [sp for r in workout_rows if r.get("source") != SOURCE and (sp := _span(r))]
    dismissed = [sp for r in dismissal_rows if (sp := _span(r))]
    detected_rows = [r for r in workout_rows if r.get("source") == SOURCE]

    keep: list[DetectedWindow] = [
        w
        for w in windows
        if not any(_overlaps(w.start, w.end, s, e, RECORDED_PAD_SEC) for s, e in recorded)
        and not any(_overlaps(w.start, w.end, s, e) for s, e in dismissed)
    ]
    wanted = {external_id_for(athlete_id, w.start) for w in keep}

    stored = {str(r.get("external_id")): r for r in detected_rows}
    for w in keep:
        prev = stored.get(external_id_for(athlete_id, w.start))
        if prev is not None and _span(prev) == (w.start, w.end) and (prev.get("avg_hr"), prev.get("max_hr")) == (
            w.avg_hr, w.max_hr
        ):
            # Unchanged since the last pass: re-saving would make the caller rebuild the
            # athlete's whole TSS history every hourly sync for nothing.
            continue
        payload = WorkoutPayload(
            source=SOURCE,
            external_id=external_id_for(athlete_id, w.start),
            sport="other",
            started_at=w.start,
            ended_at=w.end,
            duration_seconds=w.duration_sec,
            title=TITLE,
            avg_hr=w.avg_hr,
            max_hr=w.max_hr,
            **_zone_pcts(w, athlete),
        )
        await process_and_save_workout(
            payload, athlete_id, db, skip_tss_recalc=True, skip_daily_strain_refresh=True
        )
        result["saved"] += 1

    # Detections inside this day's series that the series no longer supports
    # (re-tuned thresholds, a recorded workout synced since, a window that moved).
    stale_ids = []
    for r in detected_rows:
        sp = _span(r)
        if sp is None or str(r.get("external_id")) in wanted:
            continue
        if series.start_at <= sp[0] <= series.end_at:
            stale_ids.append(r["id"])
    if stale_ids:
        await asyncio.to_thread(
            lambda: db.table("workouts").delete().eq("athlete_id", athlete_id).in_("id", stale_ids).execute()
        )
        result["removed"] = len(stale_ids)

    if result["saved"] or result["removed"]:
        await asyncio.to_thread(_refresh_daily_strain_for_day_sync, db, athlete_id, day)
    return result


def dismiss_detection(db: Any, athlete_id: str, row: dict[str, Any]) -> None:
    """Remember a deleted detection's window so it isn't detected again."""
    s = _parse_ts(row.get("started_at"))
    if s is None:
        return
    e = _parse_ts(row.get("ended_at")) or s + timedelta(seconds=int(row.get("duration_seconds") or 0))
    if e <= s:
        return
    db.table("hr_detection_dismissals").insert(
        {"athlete_id": athlete_id, "started_at": s.isoformat(), "ended_at": e.isoformat()}
    ).execute()
