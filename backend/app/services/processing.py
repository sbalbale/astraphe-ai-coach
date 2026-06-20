import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
from typing import Any

import numpy as np
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics

from app.services.algorithms import (
    compute_tss_power, 
    compute_hrss_from_zones,
    compute_trss_pace,
    compute_ctl,
    compute_atl,
    compute_sleep_score,
    compute_sleep_need,
    DEFAULT_BASELINE_SLEEP_MIN,
    MAX_SLEEP_DEBT_MIN,
    SLEEP_DEBT_DECAY_RATE,
    normalize_rowing_watts,
    compute_strain_score,
    compute_recovery_score,
    compute_readiness_score,
    calculate_rhr_baseline,
    calculate_hrv_baseline,
    calculate_spo2_baseline,
    calculate_temp_baseline,
    compute_ewma_stats,
    calculate_weekly_tss_target,
    calculate_threshold_hr_est
)

# Strava / vendor aliases → ``workouts.sport`` CHECK values (run, bike, swim, strength, row, mobility, other).
# Keys are matched case-insensitively via ``_SPORT_CANONICAL_LOOKUP``; unknown inputs → ``other``.
SPORT_CANONICAL = {
    # Rowing
    "Rowing": "row",
    "VirtualRow": "row",
    "IndoorRow": "row",
    "rowing": "row",
    # Running
    "Run": "run",
    "TrailRun": "run",
    "VirtualRun": "run",
    "running": "run",
    # Cycling
    "Ride": "bike",
    "VirtualRide": "bike",
    "EBikeRide": "bike",
    "cycling": "bike",
    # Strength
    "WeightTraining": "strength",
    "Workout": "strength",
    "Crossfit": "strength",
    "functional_fitness": "strength",
    # Mobility
    "Yoga": "mobility",
    "Stretching": "mobility",
    "Pilates": "mobility",
    # Swim
    "Swim": "swim",
    "OpenWaterSwim": "swim",
    "VirtualSwim": "swim",
    "PoolSwim": "swim",
    "LapSwim": "swim",
    "SwimInterval": "swim",
    "SwimWorkout": "swim",
    "SwimSet": "swim",
    "SwimLaps": "swim",
    "swimming": "swim",
    # Collapse to other
    "Walk": "other",
    "Hike": "other",
    # Pass-through for values already stored / sent as DB enum
    "run": "run",
    "bike": "bike",
    "swim": "swim",
    "strength": "strength",
    "row": "row",
    "mobility": "mobility",
    "other": "other",
}

_SPORT_CANONICAL_LOOKUP: dict[str, str] = {k.lower(): v for k, v in SPORT_CANONICAL.items()}

SOURCE_PRIORITY = ["strava", "intervals_icu", "garmin", "healthkit", "whoop", "manual"]

_DB_SPORTS = frozenset({"run", "bike", "swim", "strength", "row", "mobility", "other"})


def normalize_sport(raw_sport: str) -> str:
    """Map any vendor sport string to a ``workouts.sport`` value; unknown → ``other``."""
    if not raw_sport:
        return "other"
    return _SPORT_CANONICAL_LOOKUP.get(raw_sport.strip().lower(), "other")


def _sport_for_db(sport: str) -> str:
    """
    Ensure a value is safe for ``workouts.sport``. ``normalize_sport`` already returns DB
    enums; this still maps legacy intermediate names if any caller passes them.
    """
    c = (sport or "").strip().lower()
    if c in _DB_SPORTS:
        return c
    legacy = {"rowing": "row", "cycling": "bike", "walk": "other", "hike": "other"}
    return legacy.get(c, "other")


def _merge_strava_source_ids(existing_source_ids: dict[str, Any], strava_activity_id: int) -> None:
    """Accumulate every Strava activity id that maps to this canonical workout (multi-device duplicates)."""
    sid = str(int(strava_activity_id))
    raw = existing_source_ids.get("strava")
    if raw is None:
        existing_source_ids["strava"] = [sid]
        return
    if isinstance(raw, str):
        lst = [raw]
        if sid not in lst:
            lst.append(sid)
        existing_source_ids["strava"] = lst
        return
    if isinstance(raw, list):
        lst = [str(x) for x in raw]
        if sid not in lst:
            lst.append(sid)
        existing_source_ids["strava"] = lst
        return
    existing_source_ids["strava"] = [sid]


def _strava_quality_score(activity: dict | None) -> int:
    """Higher = richer Strava detail. Used to pick primary when duplicate activities merge."""
    if not activity or not isinstance(activity, dict):
        return 0
    score = 0
    if activity.get("start_latlng"):
        score += 3
    if activity.get("average_watts") or activity.get("weighted_average_watts"):
        score += 2
    if activity.get("has_heartrate") or activity.get("average_heartrate"):
        score += 1
    return score


def _strip_none_update_values(d: dict[str, Any]) -> dict[str, Any]:
    """
    PostgREST PATCH semantics: omit keys whose value is None so we do not wipe existing DB fields.

    Use ``v is not None`` only — never truthiness (``if v``), or valid numeric zeros are dropped
    (e.g. ``tss=0``, ``strain_score=0`` on rest days or very short sessions).
    """
    return {k: v for k, v in d.items() if v is not None}


def _parse_workout_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            s = val
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _workout_duration_seconds_from_row(row: dict) -> int:
    """Match GET /v1/workouts duration resolution (explicit fields, then ended - started)."""
    for k in ("duration_seconds", "duration_secs"):
        if row.get(k) is not None:
            try:
                val = int(row[k])
                if val >= 0:
                    return val
            except (TypeError, ValueError):
                pass
    start = _parse_workout_dt(row.get("started_at"))
    end = _parse_workout_dt(row.get("ended_at"))
    if start and end:
        if start.tzinfo is None and end.tzinfo is not None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None and start.tzinfo is not None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))
    return 0


def _compute_daily_strain_from_workout_rows(rows: list[dict]) -> int:
    day_zone_minutes = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    for w in rows:
        dur_sec = _workout_duration_seconds_from_row(w)
        if not dur_sec:
            continue
        for z in range(1, 6):
            pct = w.get(f"hr_zone_{z}_pct") or 0
            day_zone_minutes[z] += (float(pct) / 100.0) * (dur_sec / 60.0)
    return compute_strain_score(day_zone_minutes)


def _refresh_daily_strain_for_day_sync(db: Any, athlete_id: str, day: date) -> int:
    """Recompute biometrics.strain_score for one calendar day from stored workout zones. Returns strain 0-100."""
    day_start = day.isoformat()
    day_end = (day + timedelta(days=1)).isoformat()
    res = (
        db.table("workouts")
        .select(
            "hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct,"
            "duration_seconds,started_at,ended_at"
        )
        .eq("athlete_id", athlete_id)
        .gte("started_at", day_start)
        .lt("started_at", day_end)
        .execute()
    )
    rows = (res.data if res else None) or []
    strain = _compute_daily_strain_from_workout_rows(rows)
    db.table("biometrics").update({"strain_score": strain}).eq("athlete_id", athlete_id).eq(
        "date", day.isoformat()
    ).execute()
    return strain


def _workout_dates_for_athlete(rows: list[dict]) -> list[date]:
    dates: set[date] = set()
    for row in rows:
        started = _parse_workout_dt(row.get("started_at"))
        if started is not None:
            dates.add(started.date())
    return sorted(dates)


def refresh_all_daily_strain_sync(db: Any, athlete_id: str) -> dict[str, int]:
    """Fast path: refresh biometrics.strain_score for every day that has a workout."""
    res = (
        db.table("workouts")
        .select("started_at")
        .eq("athlete_id", athlete_id)
        .execute()
    )
    days = _workout_dates_for_athlete((res.data if res else None) or [])
    for d in days:
        _refresh_daily_strain_for_day_sync(db, athlete_id, d)
    return {"days": len(days)}


def _find_or_create_canonical_workout_sync(
    db: Any,
    athlete_id: str,
    source: str,
    sport_type: str,
    started_at: datetime,
    elapsed_time_seconds: int,
    external_id: str | None = None,
    strava_activity_id: int | None = None,
    strava_activity_payload: dict | None = None,
) -> tuple[dict, bool]:
    """
    Find an existing canonical workout that matches this session, or create a new one.
    ``sport_type`` must be a DB sport from ``normalize_sport``; ``_sport_for_db`` normalizes inserts.

    Match criteria:
      1. Exact: strava_activity_id matches (Strava fast path)
      2. Fuzzy: same athlete + sport + started_at within ±10min + duration within 20%

    On merge: updates source_ids, elevates primary_source by SOURCE_PRIORITY order.
    Strava duplicates accumulate in ``source_ids["strava"]`` (list of ids). When
    ``strava_activity_payload`` is set (Strava ingest), a richer duplicate can replace
    ``strava_activity_id`` and reset ``strava_streams_fetched`` for a re-fetch.

    On create: inserts a minimal row; caller should UPDATE full workout fields afterward.
    """
    DEDUP_WINDOW_SECONDS = 600
    DURATION_TOLERANCE = 0.20

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    db_sport = _sport_for_db(sport_type)
    dur_i = max(0, int(elapsed_time_seconds or 0))
    ended_at = started_at + timedelta(seconds=dur_i)

    if strava_activity_id is not None:
        exact = (
            db.table("workouts")
            .select("*")
            .eq("athlete_id", athlete_id)
            .eq("strava_activity_id", strava_activity_id)
            .maybe_single()
            .execute()
        )
        if exact and exact.data:
            row = exact.data
            # Same bookkeeping as fuzzy merge: source_ids + primary_source (exact path used to return early).
            existing_source_ids = dict(row.get("source_ids") or {})
            if external_id and source != "strava":
                existing_source_ids[source] = external_id
            if strava_activity_id is not None:
                _merge_strava_source_ids(existing_source_ids, strava_activity_id)
            if row.get("source") == "whoop" and row.get("external_id"):
                existing_source_ids.setdefault("whoop", str(row["external_id"]))

            current_primary = row.get("primary_source") or "manual"
            new_primary = current_primary
            if current_primary in SOURCE_PRIORITY:
                if SOURCE_PRIORITY.index(source) < SOURCE_PRIORITY.index(current_primary):
                    new_primary = source
            else:
                new_primary = source

            merge_update: dict[str, Any] = {
                "source_ids": existing_source_ids,
                "primary_source": new_primary,
            }
            merge_payload = _strip_none_update_values(merge_update)
            if merge_payload:
                updated = db.table("workouts").update(merge_payload).eq("id", row["id"]).execute()
                merged_row = (updated.data or [row])[0]
                return (merged_row, False)
            return (row, False)

    from_ts = started_at.timestamp() - DEDUP_WINDOW_SECONDS
    to_ts = started_at.timestamp() + DEDUP_WINDOW_SECONDS
    from_iso = datetime.fromtimestamp(from_ts, tz=timezone.utc).isoformat()
    to_iso = datetime.fromtimestamp(to_ts, tz=timezone.utc).isoformat()

    candidates = (
        db.table("workouts")
        .select("*")
        .eq("athlete_id", athlete_id)
        .eq("sport", db_sport)
        .gte("started_at", from_iso)
        .lte("started_at", to_iso)
        .execute()
    )
    rows = candidates.data or []

    matched = None
    for row in rows:
        existing_duration = row.get("duration_seconds") or 0
        if existing_duration > 0 and dur_i > 0:
            ratio = abs(existing_duration - dur_i) / max(existing_duration, dur_i)
            tol = DURATION_TOLERANCE
            # WHOOP vs Strava often disagree on elapsed vs moving time for the same session.
            if row.get("source") == "whoop" and source == "strava":
                tol = 0.35
            if ratio <= tol:
                matched = row
                break
        elif existing_duration == 0 or dur_i == 0:
            matched = row
            break

    if matched:
        workout_id = matched["id"]
        existing_source_ids = dict(matched.get("source_ids") or {})
        if matched.get("source") == "whoop" and matched.get("external_id"):
            existing_source_ids.setdefault("whoop", str(matched["external_id"]))
        if external_id and source != "strava":
            existing_source_ids[source] = external_id
        if strava_activity_id is not None:
            _merge_strava_source_ids(existing_source_ids, strava_activity_id)
        current_primary = matched.get("primary_source") or "manual"
        new_primary = current_primary
        if current_primary in SOURCE_PRIORITY:
            if SOURCE_PRIORITY.index(source) < SOURCE_PRIORITY.index(current_primary):
                new_primary = source
        else:
            new_primary = source

        merge_update: dict[str, Any] = {
            "source_ids": existing_source_ids,
            "primary_source": new_primary,
        }
        if strava_activity_id is not None and not matched.get("strava_activity_id"):
            merge_update["strava_activity_id"] = strava_activity_id
        elif (
            strava_activity_id is not None
            and source == "strava"
            and strava_activity_payload is not None
            and matched.get("strava_activity_id") is not None
            and int(matched["strava_activity_id"]) != int(strava_activity_id)
        ):
            existing_payload = matched.get("raw_strava_payload")
            if not isinstance(existing_payload, dict):
                existing_payload = None
            new_score = _strava_quality_score(strava_activity_payload)
            old_score = _strava_quality_score(existing_payload)
            if new_score > old_score:
                merge_update["strava_activity_id"] = strava_activity_id
                merge_update["strava_streams_fetched"] = False
                print(
                    f"[strava.dedup] Promoting activity {strava_activity_id} over "
                    f"{matched['strava_activity_id']} (score {new_score} > {old_score})"
                )
            else:
                print(
                    f"[strava.dedup] Keeping activity {matched['strava_activity_id']} as primary "
                    f"over duplicate {strava_activity_id} (scores old={old_score} new={new_score})"
                )

        merge_payload = _strip_none_update_values(merge_update)
        if merge_payload:
            updated = db.table("workouts").update(merge_payload).eq("id", workout_id).execute()
            merged_row = (updated.data or [matched])[0]
        else:
            merged_row = matched
        return (merged_row, False)

    init_source_ids: dict[str, Any] = {}
    if external_id and source != "strava":
        init_source_ids[source] = external_id
    if strava_activity_id is not None:
        _merge_strava_source_ids(init_source_ids, strava_activity_id)

    insert_row: dict[str, Any] = {
        "athlete_id": athlete_id,
        "source": source,
        "primary_source": source,
        "sport": db_sport,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": dur_i,
        "source_ids": init_source_ids,
    }
    if external_id is not None:
        insert_row["external_id"] = external_id
    if strava_activity_id is not None:
        insert_row["strava_activity_id"] = strava_activity_id

    created = db.table("workouts").insert(insert_row).execute()
    new_row = (created.data or [{}])[0]
    return (new_row, True)


async def find_or_create_canonical_workout(
    db: Any,
    athlete_id: str,
    source: str,
    sport_type: str,
    started_at: datetime,
    elapsed_time_seconds: int,
    external_id: str | None = None,
    strava_activity_id: int | None = None,
    strava_activity_payload: dict | None = None,
) -> tuple[dict, bool]:
    return await asyncio.to_thread(
        _find_or_create_canonical_workout_sync,
        db,
        athlete_id,
        source,
        sport_type,
        started_at,
        elapsed_time_seconds,
        external_id,
        strava_activity_id,
        strava_activity_payload,
    )


def _fetch_athlete_for_workout_sync(db: Any, athlete_id: str) -> dict[str, Any]:
    athlete_res = (
        db.table("athletes")
        .select("max_hr,resting_hr,threshold_hr,threshold_hr_source,threshold_pace,gender,hr_zone_method")
        .eq("id", athlete_id)
        .single()
        .execute()
    )
    return athlete_res.data if (athlete_res and athlete_res.data) else {}


def _workouts_update_by_id_sync(db: Any, workout_id: str, update_data: dict[str, Any]) -> None:
    payload = _strip_none_update_values(update_data)
    if payload:
        db.table("workouts").update(payload).eq("id", workout_id).execute()


def _parse_pace_to_sec_per_km(pace: object) -> float:
    """
    Accepts pace like '5:00', '05:00', '5:00/km', returns seconds per km.
    Returns 0.0 for invalid inputs.
    """
    if pace is None:
        return 0.0
    if isinstance(pace, (int, float)):
        return float(pace) if float(pace) > 0 else 0.0

    s = str(pace).strip().lower()
    if not s:
        return 0.0

    # remove common suffixes
    for suffix in ("/km", "per km", "km", "min/km"):
        s = s.replace(suffix, "")
    s = s.strip()

    # Support "m:ss" or "mm:ss"
    if ":" in s:
        parts = [p for p in s.split(":") if p != ""]
        if len(parts) == 2:
            try:
                mins = int(parts[0])
                secs = int(parts[1])
                total = mins * 60 + secs
                return float(total) if total > 0 else 0.0
            except Exception:
                return 0.0

    # Fallback: treat as numeric seconds
    try:
        v = float(s)
        return v if v > 0 else 0.0
    except Exception:
        return 0.0

def recalculate_tss_history(athlete_id: str, db):
    """
    Fetches all workouts for an athlete, aggregates TSS by date,
    and recalculates the entire PMC (CTL/ATL/TSB) history.

    The PMC extends through the athlete's local calendar "today": days after the last
    workout are filled with 0 TSS so CTL/ATL keep decaying and rows exist for today's
    date (avoiding bogus CTL = 0 and collapsed readiness scores on rest days).
    """
    # 1. Fetch all workouts with TSS
    res = db.table("workouts").select("started_at, tss").eq("athlete_id", athlete_id).order("started_at").execute()
    if not res or not res.data:
        return

    # 1.5 Fetch athlete timezone for correct date mapping
    athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
    offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0

    # 2. Aggregate TSS by date
    daily_tss = {}
    for w in res.data:
        # Parse ISO string and adjust for athlete's local offset
        utc_start = datetime.fromisoformat(w["started_at"].replace("Z", "+00:00"))
        local_start = utc_start + timedelta(minutes=offset)
        d = local_start.date()
        daily_tss[d] = daily_tss.get(d, 0.0) + (w["tss"] or 0.0)

    if not daily_tss:
        return

    # 3. Recalculate PMC with New proprietary Seeding Strategy
    all_dates = sorted(daily_tss.keys())
    if not all_dates:
        return

    start_date, end_date = all_dates[0], all_dates[-1]

    today_local = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
    end_date = max(end_date, today_local)

    # Extract TSS series as numpy array for compute_ctl/atl
    # Fill in missing days with 0.0
    tss_list = []
    current = start_date
    while current <= end_date:
        tss_list.append(daily_tss.get(current, 0.0))
        current += timedelta(days=1)
    
    tss_series = np.array(tss_list)
    ctl_series = compute_ctl(tss_series)
    atl_series = compute_atl(tss_series)
    
    records = []
    current = start_date
    for i in range(len(tss_series)):
        ctl = ctl_series[i]
        atl = atl_series[i]
        records.append({
            "athlete_id": athlete_id,
            "date": current.isoformat(),
            "daily_tss": round(float(tss_series[i]), 2),
            "ctl": round(float(ctl), 2),
            "atl": round(float(atl), 2),
            "tsb": round(float(ctl - atl), 2)
        })
        current += timedelta(days=1)

    # 4. Save to tss_history table
    if records:
        # Remove any stale rows that predate the earliest real workout (e.g. onboarding seeds).
        # The upsert below covers start_date..today; anything before start_date is orphaned mock data.
        db.table("tss_history").delete().eq("athlete_id", athlete_id).lt("date", start_date.isoformat()).execute()
        db.table("tss_history").upsert(records, on_conflict="athlete_id,date").execute()

async def process_and_save_workout(
    payload: WorkoutPayload,
    athlete_id: str,
    db: Any,
    skip_tss_recalc: bool = False,
    skip_daily_strain_refresh: bool = False,
) -> None:
    tss = 0.0
    wt_raw = (payload.workout_type or "").strip()
    low = wt_raw.lower()
    if low in ("gym", "strength_training"):
        wt_raw = "strength"
    elif low in ("mobility", "yoga", "stretching", "stretch", "pilates"):
        wt_raw = "mobility"
    canonical = normalize_sport(wt_raw)
    mapped_sport = _sport_for_db(canonical)

    start_utc = getattr(payload, "started_at", None) or payload.start_time
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)

    dedupe_dur = int(
        max(0, (payload.duration_seconds or getattr(payload, "elapsed_time", None) or 0))
    )
    source = payload.source or "manual"
    external_id = str(payload.external_id) if payload.external_id else None
    strava_int = int(payload.strava_activity_id) if payload.strava_activity_id is not None else None

    row, _ = await find_or_create_canonical_workout(
        db,
        athlete_id,
        source,
        canonical,
        start_utc,
        dedupe_dur,
        external_id,
        strava_int,
    )
    workout_id = row["id"]

    hr_zone_0_raw = int(getattr(payload, "hr_zone_0_pct", None) or 0)
    hr_zones = {
        1: None
        if (payload.hr_zone_1_pct is None and hr_zone_0_raw == 0)
        else int(payload.hr_zone_1_pct or 0) + hr_zone_0_raw,
        2: payload.hr_zone_2_pct,
        3: payload.hr_zone_3_pct,
        4: payload.hr_zone_4_pct,
        5: payload.hr_zone_5_pct,
    }
    has_hr_zones = any(v is not None for v in hr_zones.values())

    athlete = await asyncio.to_thread(_fetch_athlete_for_workout_sync, db, athlete_id)

    anchor_max_hr = athlete.get("max_hr") or payload.max_hr
    anchor_resting_hr = athlete.get("resting_hr")
    anchor_threshold_hr = athlete.get("threshold_hr")
    anchor_threshold_hr_source = athlete.get("threshold_hr_source")
    anchor_gender = athlete.get("gender") or "male"
    threshold_pace_sec_km = _parse_pace_to_sec_per_km(athlete.get("threshold_pace"))

    if canonical == "bike" and payload.normalized_power:
        tss = compute_tss_power(
            payload.duration_seconds, payload.normalized_power, payload.ftp_at_time
        )
    elif (
        mapped_sport == "run"
        and payload.duration_seconds
        and payload.avg_pace_sec_km
        and threshold_pace_sec_km > 0
    ):
        tss = compute_trss_pace(
            duration_sec=payload.duration_seconds,
            avg_pace_sec_km=float(payload.avg_pace_sec_km),
            threshold_pace_sec_km=float(threshold_pace_sec_km),
        )
    elif has_hr_zones and payload.duration_seconds:
        safe_hr_zones = {k: float(v or 0.0) for k, v in hr_zones.items()}

        zone_minutes = {
            k: (v / 100.0) * (payload.duration_seconds / 60.0) for k, v in safe_hr_zones.items()
        }
        # hr_zone_N_pct came from the device using its own zone boundaries at sync time.
        # If the athlete later changes hr_zone_method, these percents are not recomputed (staleness);
        # stream-derived zone analysis still uses current athlete zones.
        tss = compute_hrss_from_zones(
            zone_minutes=zone_minutes,
            max_hr=int(anchor_max_hr or 0),
            resting_hr=int(anchor_resting_hr or 0),
            threshold_hr=int(anchor_threshold_hr or 0),
            sport=mapped_sport,
            gender=str(anchor_gender),
            threshold_hr_source=anchor_threshold_hr_source,
            hr_zone_method=athlete.get("hr_zone_method"),
        )
    elif canonical == "row" and payload.average_power and payload.duration_seconds:
        norm_watts = normalize_rowing_watts(payload.average_power)
        tss = compute_tss_power(payload.duration_seconds, int(norm_watts), payload.ftp_at_time)
    elif getattr(payload, "tss", None):
        tss = getattr(payload, "tss")

    duration_seconds = payload.duration_seconds
    ended_at = payload.ended_at
    if ended_at is None and start_utc and duration_seconds:
        ended_at = start_utc + timedelta(seconds=duration_seconds)
    if duration_seconds is None and start_utc and ended_at:
        duration_seconds = int(max(0, (ended_at - start_utc).total_seconds()))

    dedupe_dur_final = int(max(0, duration_seconds or 0))
    if ended_at is None:
        ended_at = start_utc + timedelta(seconds=dedupe_dur_final)

    strain_score = 0
    if has_hr_zones and duration_seconds:
        safe_hr_zones = {k: (v or 0.0) for k, v in hr_zones.items()}
        zone_minutes = {
            k: (v / 100.0) * (duration_seconds / 60.0) for k, v in safe_hr_zones.items()
        }
        strain_score = compute_strain_score(zone_minutes)

    # Strip Nones only (_strip_none_update_values); keep tss/strain_score when they are 0.
    update_data: dict[str, Any] = {
        "sport": mapped_sport,
        "title": getattr(payload, "title", None),
        "started_at": start_utc.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_seconds": duration_seconds,
        "distance_m": payload.distance_m,
        "avg_power_w": payload.average_power,
        "avg_hr": payload.average_hr,
        "max_hr": payload.max_hr,
        "norm_power_w": payload.normalized_power,
        "avg_pace_sec_km": payload.avg_pace_sec_km,
        "tss": tss,
        "strain_score": strain_score,
        "hr_zone_1_pct": hr_zones.get(1),
        "hr_zone_2_pct": hr_zones.get(2),
        "hr_zone_3_pct": hr_zones.get(3),
        "hr_zone_4_pct": hr_zones.get(4),
        "hr_zone_5_pct": hr_zones.get(5),
    }

    await asyncio.to_thread(_workouts_update_by_id_sync, db, workout_id, update_data)
    # In batch contexts (Strava/WHOOP backfill) the caller recalculates TSS once at the end.
    if not skip_tss_recalc:
        asyncio.ensure_future(asyncio.to_thread(recalculate_tss_history, athlete_id, db))
    if not skip_daily_strain_refresh:
        workout_day = start_utc.date()
        asyncio.ensure_future(
            asyncio.to_thread(_refresh_daily_strain_for_day_sync, db, athlete_id, workout_day)
        )


def process_and_save_biometrics(
    payload: DailyBiometrics,
    athlete_id: str,
    db,
    *,
    skip_pmc_recalc: bool = False,
):
    # 1. Handle Sleep Periods (if sleep data is present)
    has_sleep_session = payload.sleep_bedtime is not None and payload.sleep_wakeup is not None
    
    if has_sleep_session:
        # Save this specific session to sleep_periods table
        # We use a helper to extract the session-specific fields
        
        # Calculate durations from timestamps to ensure consistency
        in_bed_min = 0
        if payload.sleep_bedtime and payload.sleep_wakeup:
            delta = payload.sleep_wakeup - payload.sleep_bedtime
            in_bed_min = int(round(delta.total_seconds() / 60.0))
        
        # Derive actual sleep duration: Time in Bed * (1 - Awake%)
        # This ensures mathematical integrity: Asleep + Awake = In Bed
        awake_pct = payload.sleep_awake_pct or 0.0
        actual_sleep_min = int(round(in_bed_min * (1.0 - (awake_pct / 100.0))))
        
        # If payload already has a duration, we might prefer it IF it's consistent, 
        # but the user specifically asked for the backend to handle the math.
        session_duration = actual_sleep_min
        
        session_data = {
            "athlete_id": athlete_id,
            "date": payload.date.isoformat(),
            "started_at": payload.sleep_bedtime.isoformat() if payload.sleep_bedtime else None,
            "ended_at": payload.sleep_wakeup.isoformat() if payload.sleep_wakeup else None,
            "duration_min": session_duration,
            "in_bed_min": in_bed_min,
            "score": payload.sleep_score,
            "deep_pct": payload.sleep_deep_pct,
            "rem_pct": payload.sleep_rem_pct,
            "light_pct": payload.sleep_light_pct,
            "awake_pct": payload.sleep_awake_pct,
            "is_nap": payload.is_nap or False,
            "source": payload.source,
            "external_id": getattr(payload, "external_id", None) or f"{payload.source}_{payload.sleep_bedtime.timestamp() if payload.sleep_bedtime else payload.date.isoformat()}"
        }
        db.table("sleep_periods").upsert(session_data, on_conflict="source,external_id").execute()

    # 2. Fetch All Sleep Periods for the biological day to aggregate
    all_periods_res = db.table("sleep_periods").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).execute()
    all_periods = []
    if all_periods_res and all_periods_res.data:
        all_periods = all_periods_res.data
    
    total_sleep_min = 0
    total_in_bed_min = 0
    total_awake_min = 0
    weighted_deep = 0.0
    weighted_rem = 0.0
    weighted_light = 0.0
    weighted_awake = 0.0
    
    main_sleep = None
    max_in_bed = -1
    
    for p in all_periods:
        in_bed = p.get("in_bed_min") or p.get("duration_min") or 0
        total_in_bed_min += in_bed
        
        # Calculate awake minutes for this period to ensure consistency
        awake_pct = p.get("awake_pct") or 0.0
        awake_min = (awake_pct / 100.0) * in_bed
        total_awake_min += awake_min
        
        # Weight percentages by in_bed_min
        weighted_deep += (p.get("deep_pct") or 0) * in_bed
        weighted_rem += (p.get("rem_pct") or 0) * in_bed
        weighted_light += (p.get("light_pct") or 0) * in_bed
        weighted_awake += awake_pct * in_bed
        
        if in_bed > max_in_bed:
            max_in_bed = in_bed
            main_sleep = p

    # Final aggregated architecture (weighted by in-bed duration)
    agg_deep = round(weighted_deep / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_rem = round(weighted_rem / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_light = round(weighted_light / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_awake = round(weighted_awake / total_in_bed_min, 1) if total_in_bed_min > 0 else None

    # Time Asleep MUST equal Time in Bed minus Awake Time
    total_sleep_min = int(round(total_in_bed_min - total_awake_min))
    if not all_periods and payload.sleep_duration_min is not None:
        total_sleep_min = int(max(0, payload.sleep_duration_min))
        total_in_bed_min = int(max(0, payload.sleep_in_bed_min or total_sleep_min))
        awake_pct = float(payload.sleep_awake_pct or 0.0)
        total_awake_min = max(0.0, total_in_bed_min - total_sleep_min)
        if total_awake_min == 0.0 and awake_pct > 0.0:
            total_awake_min = (awake_pct / 100.0) * total_in_bed_min
            total_sleep_min = int(round(max(0.0, total_in_bed_min - total_awake_min)))
        agg_deep = payload.sleep_deep_pct
        agg_rem = payload.sleep_rem_pct
        agg_light = payload.sleep_light_pct
        agg_awake = payload.sleep_awake_pct

    rem_sleep_min = (
        (float(agg_rem) / 100.0) * total_in_bed_min
        if agg_rem is not None and total_in_bed_min > 0
        else 0.0
    )
    deep_sleep_min = (
        (float(agg_deep) / 100.0) * total_in_bed_min
        if agg_deep is not None and total_in_bed_min > 0
        else 0.0
    )

    # 3 + 4. Fetch prev day's biometrics, 42d history, and athlete profile in parallel.
    # These three reads are fully independent, so we fan them out across a small
    # ThreadPoolExecutor and gather. Cuts ~2x off the wall time of this section.
    prev_date = payload.date - timedelta(days=1)
    start_date_42d = (payload.date - timedelta(days=42)).isoformat()

    with ThreadPoolExecutor(max_workers=3) as _ex:
        _prev_fut = _ex.submit(
            db.table("biometrics")
            .select("sleep_debt_min, strain_score")
            .eq("athlete_id", athlete_id)
            .eq("date", prev_date.isoformat())
            .maybe_single()
            .execute
        )
        _history_fut = _ex.submit(
            db.table("biometrics")
            .select("resting_hr, hrv_rmssd")
            .eq("athlete_id", athlete_id)
            .gte("date", start_date_42d)
            .order("date")
            .execute
        )
        _athlete_fut = _ex.submit(
            db.table("athletes").select("*").eq("id", athlete_id).single().execute
        )
        prev_res = _prev_fut.result()
        history_res = _history_fut.result()
        athlete_res = _athlete_fut.result()

    prev_debt = 0.0
    prev_strain = 0
    if prev_res and prev_res.data:
        prev_debt = prev_res.data.get("sleep_debt_min") or 0.0
        # Priority: Astraphe Custom Strain Score
        prev_strain = prev_res.data.get("strain_score") or 0
    
    baseline_rhr = 50.0
    baseline_hrv = 65.0
    hrv_avg_30d = baseline_hrv
    hrv_std_30d = 1.0
    rhr_avg_30d = baseline_rhr
    rhr_std_30d = 1.0
    athlete_data = athlete_res.data if athlete_res else {}
    
    if history_res and history_res.data:
        rhrs = [row["resting_hr"] for row in history_res.data if row["resting_hr"] is not None]
        hrvs = [float(row["hrv_rmssd"]) for row in history_res.data if row["hrv_rmssd"] is not None]
        
        # Include today's data in the baseline calculation
        if payload.resting_hr is not None: rhrs.append(payload.resting_hr)
        if payload.hrv_rmssd is not None: hrvs.append(payload.hrv_rmssd)
        
        if rhrs:
            baseline_rhr = calculate_rhr_baseline(rhrs)
            recent_rhrs = rhrs[-30:] if len(rhrs) >= 1 else []
            if recent_rhrs:
                rhr_avg_30d, rhr_std_30d = compute_ewma_stats(np.array(recent_rhrs, dtype=float), span=30)
        if hrvs:
            baseline_hrv = calculate_hrv_baseline(hrvs)
            recent_hrvs = hrvs[-30:] if len(hrvs) >= 1 else []
            if recent_hrvs:
                hrv_avg_30d, hrv_std_30d = compute_ewma_stats(np.array(recent_hrvs, dtype=float), span=30)

    # 4.5 Rebuild PMC first so today's CTL/ATL exist before readiness is computed.
    # Without this, tss_history has no row for today → current_ctl=0 → TSB = -ATL → readiness≈3.
    # Batch backfills pass skip_pmc_recalc=True and rebuild once at the end.
    if not skip_pmc_recalc:
        recalculate_tss_history(athlete_id, db)

    # Fetch current CTL for TSS target calculation (now guaranteed to exist for today)
    ctl_res = db.table("tss_history").select("ctl").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).maybe_single().execute()
    current_ctl = ctl_res.data["ctl"] if (ctl_res and ctl_res.data) else 0.0
    
    profile_updates = {
        "rhr_baseline": int(round(baseline_rhr)),
        "hrv_baseline": round(baseline_hrv, 1),
        "resting_hr": int(round(baseline_rhr)), # Sync current resting_hr with baseline
        "weekly_tss_target": calculate_weekly_tss_target(current_ctl)
    }
    
    # Estimate Threshold HR if missing (using HRR method: 83% intensity)
    if athlete_data.get("max_hr") and not athlete_data.get("threshold_hr"):
        profile_updates["threshold_hr"] = calculate_threshold_hr_est(
            max_hr=athlete_data["max_hr"],
            resting_hr=int(round(baseline_rhr))
        )
        profile_updates["threshold_hr_source"] = "estimated"
    
    db.table("athletes").update(profile_updates).eq("id", athlete_id).execute()
    
    # 5. Fetch ATL Data for Readiness Modeling
    start_date_30d = (payload.date - timedelta(days=30)).isoformat()
    atl_res = db.table("tss_history").select("atl").eq("athlete_id", athlete_id).gte("date", start_date_30d).order("date").execute()
    
    prior_day_atl = 0.0
    prior_day_atl_max_30d = 1.0 
    
    if atl_res and atl_res.data:
        atls = [row["atl"] for row in atl_res.data if row["atl"] is not None]
        if atls:
            prior_day_atl_max_30d = max(atls) or 1.0
            prior_day_atl = atls[-1]
            
    # 6. Process Sleep Architecture (Aggregated) — strict sleep score (minutes in / out of bed)
    # Sleep need uses baseline + strain/debt impact.
    carried_debt = float(prev_debt or 0.0) * SLEEP_DEBT_DECAY_RATE
    sleep_need = compute_sleep_need(
        baseline_min=DEFAULT_BASELINE_SLEEP_MIN,
        strain_score=int(prev_strain or 0),
        current_debt_min=carried_debt,
    )
    
    sleep_score = compute_sleep_score(
        actual_sleep_min=total_sleep_min,
        sleep_need_min=sleep_need,
        rem_min=rem_sleep_min,
        deep_min=deep_sleep_min,
        awake_min=total_awake_min,
    )

    next_night_debt = float(np.clip(float(sleep_need) - float(total_sleep_min), 0.0, MAX_SLEEP_DEBT_MIN))

    # 7. Merge with existing Biometrics row (HRV/RHR/Strain)
    existing_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).maybe_single().execute()
    existing = {}
    if existing_res and existing_res.data:
        existing = existing_res.data

    # 7.5 Calculate Daily Astraphe Strain from Workouts
    day_workouts_res = (
        db.table("workouts")
        .select(
            "hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct,"
            "duration_seconds,started_at,ended_at"
        )
        .eq("athlete_id", athlete_id)
        .gte("started_at", payload.date.isoformat())
        .lt("started_at", (payload.date + timedelta(days=1)).isoformat())
        .execute()
    )
    day_rows = (day_workouts_res.data if day_workouts_res else None) or []
    astraphe_strain_score = _compute_daily_strain_from_workout_rows(day_rows)

    final_hrv = payload.hrv_rmssd if payload.hrv_rmssd is not None else existing.get("hrv_rmssd")
    final_rhr = payload.resting_hr if payload.resting_hr is not None else existing.get("resting_hr")
    final_temp = payload.skin_temp if payload.skin_temp is not None else existing.get("skin_temp")
    final_spo2 = payload.spo2_pct if payload.spo2_pct is not None else existing.get("spo2_pct")
    final_source = payload.source if payload.hrv_rmssd is not None else existing.get("hrv_source", payload.source)

    # 8. Process Recovery (Autonomic Repair)
    # Only recompute when HRV data is present — defaulting to 0.0 produces z_hrv≈-65
    # which collapses the score to near zero and would overwrite a good recovery score
    # from a race-condition where sleep.updated fires before recovery.updated.
    if final_hrv is not None and final_rhr is not None:
        recovery_score = compute_recovery_score(
            hrv_today=final_hrv,
            hrv_avg_30d=hrv_avg_30d,
            hrv_std_30d=hrv_std_30d,
            rhr_today=final_rhr,
            rhr_avg_30d=rhr_avg_30d,
            rhr_std_30d=rhr_std_30d,
            sleep_score=sleep_score,
            prior_day_atl=prior_day_atl,
            prior_day_atl_max_30d=prior_day_atl_max_30d,
        )
    else:
        recovery_score = existing.get("recovery_score")
    
    # 9. Process Readiness (Capacity to Train)
    # TSB based readiness
    readiness_score = compute_readiness_score(current_ctl - prior_day_atl)
    
    # 10. Save aggregated record to biometrics
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "hrv_rmssd": final_hrv,
        "resting_hr": int(round(final_rhr)) if final_rhr is not None else None,
        "weight_kg": payload.weight_kg if payload.weight_kg is not None else existing.get("weight_kg"),
        "height_cm": payload.height_cm if payload.height_cm is not None else existing.get("height_cm"),
        "sleep_duration_min": total_sleep_min,
        "sleep_in_bed_min": total_in_bed_min,
        "sleep_score": sleep_score, # Astraphe Score
        "recovery_score": recovery_score, # Astraphe Score
        "sleep_need_min": int(round(sleep_need)),
        "sleep_debt_min": int(round(next_night_debt)),
        "readiness_score": readiness_score,
        "strain_score": astraphe_strain_score,
        "hrv_source": final_source,
        "sleep_deep_pct": agg_deep,
        "sleep_rem_pct": agg_rem,
        "sleep_light_pct": agg_light,
        "sleep_awake_pct": agg_awake,
        "sleep_bedtime": main_sleep.get("started_at") if main_sleep else None,
        "sleep_wakeup": main_sleep.get("ended_at") if main_sleep else None,
        "skin_temp": final_temp,
        "spo2_pct": final_spo2
        }, on_conflict="athlete_id,date").execute()


def _workout_row_to_payload(row: dict) -> WorkoutPayload:
    """Build a WorkoutPayload from a stored workouts row for TSS/strain recomputation."""
    return WorkoutPayload(
        source=row.get("source") or "manual",
        external_id=row.get("external_id"),
        strava_activity_id=row.get("strava_activity_id"),
        sport=row.get("sport") or "other",
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
        duration_seconds=row.get("duration_seconds"),
        distance_m=row.get("distance_m"),
        avg_power_w=row.get("avg_power_w"),
        norm_power_w=row.get("norm_power_w"),
        avg_hr=row.get("avg_hr"),
        max_hr=row.get("max_hr"),
        avg_pace_sec_km=row.get("avg_pace_sec_km"),
        tss=None,
        title=row.get("title"),
        hr_zone_0_pct=row.get("hr_zone_0_pct"),
        hr_zone_1_pct=row.get("hr_zone_1_pct"),
        hr_zone_2_pct=row.get("hr_zone_2_pct"),
        hr_zone_3_pct=row.get("hr_zone_3_pct"),
        hr_zone_4_pct=row.get("hr_zone_4_pct"),
        hr_zone_5_pct=row.get("hr_zone_5_pct"),
    )


async def recompute_workout_tss_for_athlete(athlete_id: str, db) -> int:
    """Recompute TSS/strain for workouts missing tss. Returns count updated."""
    res = db.table("workouts").select("*").eq("athlete_id", athlete_id).order("started_at").execute()
    updated = 0
    for row in res.data or []:
        if row.get("tss") is not None:
            continue
        await process_and_save_workout(_workout_row_to_payload(row), athlete_id, db, skip_tss_recalc=True)
        updated += 1
    return updated


async def reprocess_athlete_metrics(athlete_id: str, db) -> dict[str, int]:
    """Rebuild workout TSS, biometrics aggregates, and PMC (CTL/ATL/TSB) for one athlete."""
    workouts_res = db.table("workouts").select("*").eq("athlete_id", athlete_id).order("started_at").execute()
    workout_count = 0
    for row in workouts_res.data or []:
        await process_and_save_workout(
            _workout_row_to_payload(row),
            athlete_id,
            db,
            skip_tss_recalc=True,
            skip_daily_strain_refresh=True,
        )
        workout_count += 1

    biometrics_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date").execute()
    bio_count = 0
    for b in biometrics_res.data or []:
        payload = DailyBiometrics(
            date=b["date"],
            source=b.get("hrv_source") or "whoop",
            hrv_rmssd=float(b["hrv_rmssd"]) if b.get("hrv_rmssd") is not None else None,
            resting_hr=b.get("resting_hr"),
            weight_kg=float(b["weight_kg"]) if b.get("weight_kg") is not None else None,
            height_cm=float(b["height_cm"]) if b.get("height_cm") is not None else None,
            sleep_duration_min=None,
            sleep_score=b.get("sleep_score"),
            sleep_deep_pct=float(b["sleep_deep_pct"]) if b.get("sleep_deep_pct") is not None else None,
            sleep_rem_pct=float(b["sleep_rem_pct"]) if b.get("sleep_rem_pct") is not None else None,
            sleep_light_pct=float(b["sleep_light_pct"]) if b.get("sleep_light_pct") is not None else None,
            sleep_awake_pct=float(b["sleep_awake_pct"]) if b.get("sleep_awake_pct") is not None else None,
            sleep_bedtime=None,
            sleep_wakeup=None,
            skin_temp=float(b["skin_temp"]) if b.get("skin_temp") is not None else None,
            spo2_pct=float(b["spo2_pct"]) if b.get("spo2_pct") is not None else None,
            recovery_score=b.get("recovery_score"),
        )
        process_and_save_biometrics(payload, athlete_id, db, skip_pmc_recalc=True)
        bio_count += 1

    recalculate_tss_history(athlete_id, db)
    return {"workouts": workout_count, "biometrics": bio_count}

