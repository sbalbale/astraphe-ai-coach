"""
Shared workout query/format helpers for coach tools and routers.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from supabase import Client

from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.hr_zones import get_athlete_zones
from app.services.processing import (
    find_or_create_canonical_workout,
    normalize_sport,
    process_and_save_biometrics,
    process_and_save_workout,
    recalculate_tss_history,
    _refresh_daily_strain_for_day_sync,
)
from app.services.stream_storage import fetch_stream_row_columns
from app.services.time_utils import (
    athlete_local_date,
    athlete_local_datetime,
    fetch_athlete_timezone_offset_min,
)

WORKOUT_LIST_COLUMNS = (
    "id, athlete_id, source, sport, title, started_at, ended_at, duration_seconds, "
    "distance_m, avg_hr, max_hr, avg_power_w, norm_power_w, avg_pace_sec_km, tss, "
    "strain_score, strava_activity_id, strava_streams_fetched, intervals_source, "
    "hr_zone_0_pct, hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, "
    "hr_zone_5_pct, elevation_gain_m, primary_source, source_ids"
)

LIST_WORKOUTS_MAX = 25
STREAM_WINDOW_MAX_MIN = 15
STREAM_TARGET_POINTS = 45
TRAINING_LOAD_DEFAULT_DAYS = 42
BIOMETRICS_DATES_MAX = 7
SUMMARIZE_WORKOUTS_MAX = 100

METRIC_KEYS = {
    "hr": ("heartrate", "bpm"),
    "power": ("watts", "w"),
    "pace": ("pace", "sec_km"),
    "cadence": ("cadence", "rpm"),
}


def parse_coach_date(raw: str | None, *, default: date | None = None) -> date:
    if raw is None or not str(raw).strip():
        if default is None:
            raise ValueError("date is required")
        return default
    return date.fromisoformat(str(raw).strip()[:10])


def normalize_coach_sport(raw: str) -> str:
    sport_norm = str(raw or "").strip().lower()
    if sport_norm in ("bike", "biking", "cycling", "cycle", "ride"):
        return "bike"
    if sport_norm in ("run", "running", "jogging"):
        return "run"
    if sport_norm in ("swim", "swimming"):
        return "swim"
    if sport_norm in ("row", "rowing", "erg"):
        return "row"
    if sport_norm in ("strength", "gym", "lifting", "weights"):
        return "strength"
    if sport_norm in ("mobility", "yoga", "stretching", "stretch"):
        return "mobility"
    return "other"


def _local_day_utc_bounds(on_date: date, offset_min: int) -> tuple[datetime, datetime]:
    tz = timezone(timedelta(minutes=offset_min))
    start_local = datetime(on_date.year, on_date.month, on_date.day, 0, 0, 0, tzinfo=tz)
    end_local = datetime(on_date.year, on_date.month, on_date.day, 23, 59, 59, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def resolve_local_start_utc(
    db: Client,
    athlete_id: str,
    on_date: date,
    start_time_local: str | None,
) -> datetime:
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    tz = timezone(timedelta(minutes=offset))
    today_local = athlete_local_date(db, athlete_id)

    if start_time_local and str(start_time_local).strip():
        parts = str(start_time_local).strip().split(":")
        hrs = int(parts[0])
        mins = int(parts[1]) if len(parts) > 1 else 0
    elif on_date == today_local:
        now_local = athlete_local_datetime(db, athlete_id)
        hrs, mins = now_local.hour, now_local.minute
    else:
        hrs, mins = 12, 0

    start_local = datetime(on_date.year, on_date.month, on_date.day, hrs, mins, 0, tzinfo=tz)
    return start_local.astimezone(timezone.utc)


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
        except Exception:
            return None
    return None


def _duration_secs(row: dict[str, Any]) -> int | None:
    for k in ("duration_secs", "duration_seconds"):
        if row.get(k) is not None:
            try:
                val = int(row.get(k))
                if val >= 0:
                    return val
            except Exception:
                pass
    start = _parse_dt(row.get("started_at"))
    end = _parse_dt(row.get("ended_at"))
    if start and end:
        if start.tzinfo is None and end.tzinfo is not None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None and start.tzinfo is not None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))
    return None


def _compact_list_row(row: dict[str, Any]) -> dict[str, Any]:
    dur = _duration_secs(row)
    dist_m = row.get("distance_m")
    return {
        "id": row.get("id"),
        "sport": row.get("sport"),
        "title": row.get("title"),
        "started_at": row.get("started_at"),
        "duration_min": round(dur / 60.0, 1) if dur is not None else None,
        "distance_km": round(float(dist_m) / 1000.0, 2) if dist_m is not None else None,
        "tss": row.get("tss"),
        "strain_score": row.get("strain_score"),
        "avg_hr": row.get("avg_hr"),
        "avg_power_w": row.get("avg_power_w"),
        "source": row.get("primary_source") or row.get("source"),
    }


def recent_workouts_teaser(db: Client, athlete_id: str, limit: int = 2) -> list[dict[str, Any]]:
    """Compact last-N completed workouts for system context (id, sport, date, tss)."""
    rows = query_workouts(db, athlete_id, limit=limit)
    teaser: list[dict[str, Any]] = []
    for row in rows:
        started = row.get("started_at")
        local_date = str(started)[:10] if started else None
        teaser.append(
            {
                "id": row.get("id"),
                "sport": row.get("sport"),
                "date": local_date,
                "tss": row.get("tss"),
                "duration_min": _compact_list_row(row).get("duration_min"),
            }
        )
    return teaser


def format_workout_summary(row: dict[str, Any], *, lap_count: int | None = None) -> dict[str, Any]:
    dur = _duration_secs(row)
    dist_m = row.get("distance_m")
    summary: dict[str, Any] = {
        "id": row.get("id"),
        "title": row.get("title"),
        "sport": row.get("sport"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "duration_min": round(dur / 60.0, 1) if dur is not None else None,
        "distance_km": round(float(dist_m) / 1000.0, 2) if dist_m is not None else None,
        "source": row.get("primary_source") or row.get("source"),
        "tss": row.get("tss"),
        "strain_score": row.get("strain_score"),
        "norm_power_w": row.get("norm_power_w"),
        "avg_hr": row.get("avg_hr"),
        "max_hr": row.get("max_hr"),
        "avg_power_w": row.get("avg_power_w"),
        "elevation_gain_m": row.get("elevation_gain_m"),
        "hr_zone_1_pct": row.get("hr_zone_1_pct"),
        "hr_zone_2_pct": row.get("hr_zone_2_pct"),
        "hr_zone_3_pct": row.get("hr_zone_3_pct"),
        "hr_zone_4_pct": row.get("hr_zone_4_pct"),
        "hr_zone_5_pct": row.get("hr_zone_5_pct"),
        "strava_streams_fetched": row.get("strava_streams_fetched"),
    }
    if lap_count is not None:
        summary["lap_count"] = lap_count
    intervals = row.get("intervals")
    if isinstance(intervals, list):
        summary["interval_count"] = len(intervals)
    return summary


def query_workouts(
    db: Client,
    athlete_id: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    on_date: date | None = None,
    sport: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), LIST_WORKOUTS_MAX))
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)

    q = (
        db.table("workouts")
        .select(WORKOUT_LIST_COLUMNS)
        .eq("athlete_id", athlete_id)
    )

    if on_date is not None:
        from_utc, to_utc = _local_day_utc_bounds(on_date, offset)
        q = q.gte("started_at", from_utc.isoformat()).lte("started_at", to_utc.isoformat())
    else:
        if start_date is not None:
            from_utc, _ = _local_day_utc_bounds(start_date, offset)
            q = q.gte("started_at", from_utc.isoformat())
        if end_date is not None:
            _, to_utc = _local_day_utc_bounds(end_date, offset)
            q = q.lte("started_at", to_utc.isoformat())

    if sport:
        q = q.eq("sport", normalize_coach_sport(sport))

    res = q.order("started_at", desc=True).limit(limit).execute()
    return list(res.data or [])


def fetch_workout_by_id(db: Client, athlete_id: str, workout_id: str) -> dict[str, Any] | None:
    res = (
        db.table("workouts")
        .select(WORKOUT_LIST_COLUMNS)
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


def resolve_workout_row(
    db: Client,
    athlete_id: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    workout_id = args.get("workout_id")
    if workout_id:
        return fetch_workout_by_id(db, athlete_id, str(workout_id))

    on_date_raw = args.get("on_date")
    sport_raw = args.get("sport")
    if not on_date_raw or not sport_raw:
        return None

    on_date = parse_coach_date(str(on_date_raw))
    rows = query_workouts(
        db,
        athlete_id,
        on_date=on_date,
        sport=str(sport_raw),
        limit=LIST_WORKOUTS_MAX,
    )
    if not rows:
        return None
    return rows[0]


def _count_laps(db: Client, athlete_id: str, workout_id: str) -> int | None:
    try:
        res = (
            db.table("activity_laps")
            .select("id")
            .eq("workout_id", workout_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        return len(res.data or [])
    except Exception:
        return None


def get_workout_summary(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    row = resolve_workout_row(db, athlete_id, args)
    if not row:
        return {"error": "workout_not_found"}
    lap_count = _count_laps(db, athlete_id, str(row["id"]))
    return format_workout_summary(row, lap_count=lap_count)


def _downsample(values: list[float], target: int) -> list[float]:
    if len(values) <= target:
        return values
    step = len(values) / target
    out: list[float] = []
    for i in range(target):
        idx = int(i * step)
        if idx < len(values):
            out.append(values[idx])
    return out


def slice_stream_window(
    db: Client,
    athlete_id: str,
    workout_id: str,
    *,
    start_offset_min: float,
    end_offset_min: float,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    if end_offset_min < start_offset_min:
        return {"error": "invalid_window", "message": "end_offset_min must be >= start_offset_min"}
    if (end_offset_min - start_offset_min) > STREAM_WINDOW_MAX_MIN:
        return {
            "error": "window_too_large",
            "message": f"Window max {STREAM_WINDOW_MAX_MIN} minutes",
        }

    row = fetch_stream_row_columns(db, workout_id, athlete_id)
    if not row or not row.get("time_series"):
        return {"error": "streams_unavailable", "workout_id": workout_id}

    time_series = row.get("time_series") or {}
    resolution = int(row.get("resolution_seconds") or 1)
    start_sec = int(start_offset_min * 60)
    end_sec = int(end_offset_min * 60)
    start_idx = max(0, start_sec // max(1, resolution))
    end_idx = max(start_idx, end_sec // max(1, resolution))

    requested = metrics or ["hr", "power"]
    requested = [m.lower() for m in requested if m.lower() in METRIC_KEYS]

    result: dict[str, Any] = {
        "workout_id": workout_id,
        "start_offset_min": start_offset_min,
        "end_offset_min": end_offset_min,
        "resolution_seconds": resolution,
        "metrics": {},
    }

    for metric in requested:
        key, unit = METRIC_KEYS[metric]
        series = time_series.get(key)
        if not isinstance(series, list) or not series:
            continue
        window = series[start_idx : end_idx + 1]
        nums = [float(v) for v in window if v is not None]
        if not nums:
            continue
        ds = _downsample(nums, STREAM_TARGET_POINTS)
        result["metrics"][metric] = {
            "unit": unit,
            "min": round(min(nums), 2),
            "max": round(max(nums), 2),
            "avg": round(sum(nums) / len(nums), 2),
            "points": [round(v, 2) for v in ds],
        }

    if not result["metrics"]:
        return {"error": "streams_unavailable", "workout_id": workout_id}

    return result


def fetch_athlete_ftp(db: Client, athlete_id: str) -> int:
    try:
        res = (
            db.table("athletes")
            .select("ftp_watts")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = res.data or {}
        ftp = row.get("ftp_watts")
        return int(ftp) if ftp else 250
    except Exception:
        return 250


def build_log_workout_payload(
    db: Client,
    athlete_id: str,
    args: dict[str, Any],
) -> WorkoutPayload:
    sport = normalize_coach_sport(str(args.get("sport", "")))
    if not args.get("sport"):
        raise ValueError("sport is required")

    try:
        duration_minutes = int(args.get("duration_minutes", 0))
    except (TypeError, ValueError) as e:
        raise ValueError("duration_minutes must be an integer") from e
    if duration_minutes < 1 or duration_minutes > 720:
        raise ValueError("duration_minutes must be between 1 and 720")

    on_date = parse_coach_date(
        args.get("on_date"),
        default=athlete_local_date(db, athlete_id),
    )
    start_utc = resolve_local_start_utc(
        db,
        athlete_id,
        on_date,
        args.get("start_time_local"),
    )
    duration_seconds = duration_minutes * 60
    ended_utc = start_utc + timedelta(seconds=duration_seconds)

    avg_power = args.get("avg_power_w")
    norm_power = args.get("norm_power_w")
    if avg_power is not None:
        avg_power = int(avg_power)
        if avg_power < 1 or avg_power > 2000:
            raise ValueError("avg_power_w out of range")
    if norm_power is not None:
        norm_power = int(norm_power)
    elif avg_power is not None and sport == "bike":
        norm_power = avg_power

    title = str(args.get("title") or "").strip()
    if not title:
        title = f"{sport.title()} — {duration_minutes}m"

    return WorkoutPayload(
        source="manual",
        sport=sport,
        started_at=start_utc,
        ended_at=ended_utc,
        duration_seconds=duration_seconds,
        average_power=avg_power,
        normalized_power=norm_power,
        average_hr=int(args["avg_hr"]) if args.get("avg_hr") is not None else None,
        max_hr=int(args["max_hr"]) if args.get("max_hr") is not None else None,
        distance_m=float(args["distance_m"]) if args.get("distance_m") is not None else None,
        avg_pace_sec_km=int(args["avg_pace_sec_km"]) if args.get("avg_pace_sec_km") is not None else None,
        tss=float(args["tss"]) if args.get("tss") is not None else None,
        title=title,
        ftp_at_time=fetch_athlete_ftp(db, athlete_id),
    )


async def save_logged_workout(
    db: Client,
    athlete_id: str,
    payload: WorkoutPayload,
) -> tuple[str, bool]:
    start_utc = payload.start_time
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    canonical = normalize_sport(payload.workout_type)
    dur = int(payload.duration_seconds or 0)
    row, is_new = await find_or_create_canonical_workout(
        db,
        athlete_id,
        payload.source or "manual",
        canonical,
        start_utc,
        dur,
        None,
        None,
    )
    await process_and_save_workout(payload, athlete_id, db)
    return str(row["id"]), is_new


def log_workout_sync(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = build_log_workout_payload(db, athlete_id, args)
    except ValueError as e:
        return {"error": str(e)}

    try:
        workout_id, is_new = asyncio.run(save_logged_workout(db, athlete_id, payload))
    except Exception as e:
        return {"error": f"log_workout_failed: {e}"}

    saved = fetch_workout_by_id(db, athlete_id, workout_id)
    if not saved:
        return {"error": "workout_saved_but_not_found", "workout_id": workout_id}

    dur = _duration_secs(saved)
    tss = saved.get("tss")
    msg = f"Logged {round((dur or 0) / 60)} min {saved.get('sport')} (TSS {tss})."
    if not is_new:
        msg = f"Updated existing {saved.get('sport')} entry (TSS {tss})."

    return {
        "status": "created" if is_new else "merged",
        "workout_id": workout_id,
        "sport": saved.get("sport"),
        "started_at": saved.get("started_at"),
        "duration_min": round(dur / 60.0, 1) if dur else None,
        "avg_power_w": saved.get("avg_power_w"),
        "tss": tss,
        "message": msg,
    }


def list_workouts_compact(
    db: Client,
    athlete_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        return {"error": "limit must be an integer"}

    on_date = None
    start_date = None
    end_date = None
    try:
        if args.get("on_date"):
            on_date = parse_coach_date(str(args["on_date"]))
        if args.get("start_date"):
            start_date = parse_coach_date(str(args["start_date"]))
        if args.get("end_date"):
            end_date = parse_coach_date(str(args["end_date"]))
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    rows = query_workouts(
        db,
        athlete_id,
        start_date=start_date,
        end_date=end_date,
        on_date=on_date,
        sport=str(args["sport"]) if args.get("sport") else None,
        limit=limit,
    )
    return {"count": len(rows), "workouts": [_compact_list_row(r) for r in rows]}


def _workout_patch_from_args(
    db: Client,
    athlete_id: str,
    existing: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    update: dict[str, Any] = {}

    if args.get("title") is not None:
        t = str(args["title"]).strip()
        update["title"] = t or None

    for arg_key, col in (
        ("avg_power_w", "avg_power_w"),
        ("norm_power_w", "norm_power_w"),
        ("avg_hr", "avg_hr"),
        ("max_hr", "max_hr"),
        ("distance_m", "distance_m"),
        ("tss", "tss"),
    ):
        if args.get(arg_key) is not None:
            update[col] = args[arg_key]

    start = _parse_dt(existing.get("started_at"))
    duration = _duration_secs(existing)

    if args.get("duration_minutes") is not None:
        duration = int(args["duration_minutes"]) * 60
        update["duration_seconds"] = duration

    if args.get("on_date"):
        on_date = parse_coach_date(str(args["on_date"]))
        offset_min = fetch_athlete_timezone_offset_min(db, athlete_id)
        tz = timezone(timedelta(minutes=offset_min))
        if start:
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            local = start.astimezone(tz)
        else:
            local = athlete_local_datetime(db, athlete_id)
        new_local = datetime(
            on_date.year, on_date.month, on_date.day,
            local.hour, local.minute, tzinfo=tz,
        )
        start = new_local.astimezone(timezone.utc)
        update["started_at"] = start.isoformat()

    if start and duration is not None:
        ended = start + timedelta(seconds=duration)
        update["ended_at"] = ended.isoformat()
        if "duration_seconds" not in update:
            update["duration_seconds"] = duration

    return update


def update_workout_sync(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    row = resolve_workout_row(db, athlete_id, args)
    if not row:
        return {"error": "workout_not_found"}

    update_data = _workout_patch_from_args(db, athlete_id, row, args)
    if not update_data:
        return {"error": "no_fields_to_update"}

    workout_id = str(row["id"])
    try:
        db.table("workouts").update(update_data).eq("id", workout_id).eq("athlete_id", athlete_id).execute()
        recalculate_tss_history(athlete_id, db)
        started = _parse_dt(update_data.get("started_at") or row.get("started_at"))
        if started:
            _refresh_daily_strain_for_day_sync(db, athlete_id, started.date())
    except Exception as e:
        return {"error": f"update_workout_failed: {e}"}

    saved = fetch_workout_by_id(db, athlete_id, workout_id)
    return {
        "status": "updated",
        "workout_id": workout_id,
        "summary": format_workout_summary(saved or row),
    }


def log_biometrics_sync(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    on_date = parse_coach_date(
        args.get("on_date"),
        default=athlete_local_date(db, athlete_id),
    )
    fields: dict[str, Any] = {"date": on_date, "source": "manual"}
    for key in (
        "sleep_duration_min",
        "sleep_score",
        "resting_hr",
        "hrv_rmssd",
        "weight_kg",
    ):
        if args.get(key) is not None:
            fields[key] = args[key]

    if args.get("sleep_bedtime") and args.get("sleep_wakeup"):
        fields["sleep_bedtime"] = _parse_dt(args["sleep_bedtime"])
        fields["sleep_wakeup"] = _parse_dt(args["sleep_wakeup"])

    if len(fields) <= 2:
        return {"error": "no_biometric_fields_provided"}

    try:
        payload = DailyBiometrics(**fields)
        process_and_save_biometrics(payload, athlete_id, db)
    except Exception as e:
        return {"error": f"log_biometrics_failed: {e}"}

    return {"status": "saved", "date": on_date.isoformat(), "fields": list(fields.keys())}


def get_athlete_zones_payload(db: Client, athlete_id: str) -> dict[str, Any]:
    try:
        res = (
            db.table("athletes")
            .select(
                "lthr, threshold_hr, max_hr, resting_hr, hr_zone_method, ftp_watts, threshold_pace"
            )
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        athlete = res.data or {}
    except Exception as e:
        return {"error": f"athlete_query_failed: {e}"}

    zones = get_athlete_zones(athlete)
    return {
        "ftp_watts": athlete.get("ftp_watts"),
        "threshold_pace": athlete.get("threshold_pace"),
        "anchors": {
            "lthr": athlete.get("lthr") or athlete.get("threshold_hr"),
            "max_hr": athlete.get("max_hr"),
            "resting_hr": athlete.get("resting_hr"),
            "method": athlete.get("hr_zone_method") or "lthr",
        },
        "zones": [
            {"zone": z.zone, "name": z.name, "min_bpm": z.min_bpm, "max_bpm": z.max_bpm}
            for z in zones
        ],
    }


def query_planned_workouts(
    db: Client,
    athlete_id: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    res = (
        db.table("training_plans")
        .select("id, planned_date, sport, title, duration_min, target_tss, primary_zone, status")
        .eq("athlete_id", athlete_id)
        .gte("planned_date", start_date.isoformat())
        .lte("planned_date", end_date.isoformat())
        .order("planned_date")
        .execute()
    )
    return list(res.data or [])


def resolve_plan_row(
    db: Client,
    athlete_id: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    plan_id = args.get("plan_id")
    if plan_id:
        res = (
            db.table("training_plans")
            .select("*")
            .eq("id", str(plan_id))
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
        )
        return res.data if res and res.data else None

    on_date_raw = args.get("on_date") or args.get("date")
    sport_raw = args.get("sport")
    if not on_date_raw:
        return None
    on_date = parse_coach_date(str(on_date_raw))
    rows = query_planned_workouts(db, athlete_id, on_date, on_date)
    if sport_raw:
        sport = normalize_coach_sport(str(sport_raw))
        rows = [r for r in rows if r.get("sport") == sport]
    return rows[0] if rows else None


def update_planned_workout_sync(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    row = resolve_plan_row(db, athlete_id, args)
    if not row:
        return {"error": "plan_not_found"}

    update: dict[str, Any] = {}
    if args.get("new_date"):
        update["planned_date"] = parse_coach_date(str(args["new_date"])).isoformat()
    if args.get("duration_minutes") is not None:
        update["duration_min"] = int(args["duration_minutes"])
    if args.get("sport"):
        update["sport"] = normalize_coach_sport(str(args["sport"]))
    if args.get("title"):
        update["title"] = str(args["title"])
    if args.get("focus_zone"):
        update["primary_zone"] = str(args["focus_zone"])
    if isinstance(args.get("structure"), list):
        update["structure"] = args["structure"]
        update["status"] = "modified"

    if not update:
        return {"error": "no_fields_to_update"}

    plan_id = str(row["id"])
    try:
        upd = (
            db.table("training_plans")
            .update(update)
            .eq("id", plan_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        saved = (upd.data or [row])[0]
    except Exception as e:
        return {"error": f"update_plan_failed: {e}"}

    return {"status": "updated", "plan_id": plan_id, "plan": saved}


def delete_planned_workout_sync(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    row = resolve_plan_row(db, athlete_id, args)
    if not row:
        return {"error": "plan_not_found"}

    plan_id = str(row["id"])
    try:
        db.table("training_plans").delete().eq("id", plan_id).eq("athlete_id", athlete_id).execute()
    except Exception as e:
        return {"error": f"delete_plan_failed: {e}"}

    return {"status": "deleted", "plan_id": plan_id, "planned_date": row.get("planned_date")}


def _resolve_date_range(
    db: Client,
    athlete_id: str,
    args: dict[str, Any],
    *,
    default_days_back: int = 7,
) -> tuple[date, date]:
    today = athlete_local_date(db, athlete_id)
    if args.get("start_date"):
        start = parse_coach_date(str(args["start_date"]))
    else:
        start = today - timedelta(days=default_days_back)
    if args.get("end_date"):
        end = parse_coach_date(str(args["end_date"]))
    else:
        end = today
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    return start, end


def _period_bounds(db: Client, athlete_id: str, period: str) -> tuple[date, date]:
    today = athlete_local_date(db, athlete_id)
    p = str(period).strip().lower()
    if p == "week":
        return today - timedelta(days=6), today
    if p == "month":
        return today - timedelta(days=29), today
    raise ValueError("period must be 'week' or 'month'")


def _compact_plan_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "planned_date": row.get("planned_date"),
        "sport": row.get("sport"),
        "title": row.get("title"),
        "duration_min": row.get("duration_min"),
        "target_tss": row.get("target_tss"),
        "primary_zone": row.get("primary_zone"),
        "status": row.get("status"),
    }


def list_planned_workouts_compact(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        today = athlete_local_date(db, athlete_id)
        start = parse_coach_date(args.get("start_date"), default=today)
        end = parse_coach_date(args.get("end_date"), default=today + timedelta(days=7))
        if end < start:
            return {"error": "end_date must be on or after start_date"}
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    rows = query_planned_workouts(db, athlete_id, start, end)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(rows),
        "plans": [_compact_plan_row(r) for r in rows],
    }


def get_training_load_series(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        today = athlete_local_date(db, athlete_id)
        end = parse_coach_date(args.get("end_date"), default=today)
        start = parse_coach_date(
            args.get("start_date"),
            default=end - timedelta(days=TRAINING_LOAD_DEFAULT_DAYS - 1),
        )
        if end < start:
            return {"error": "end_date must be on or after start_date"}
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    try:
        res = (
            db.table("tss_history")
            .select("date,daily_tss,ctl,atl,tsb")
            .eq("athlete_id", athlete_id)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .order("date")
            .execute()
        )
        rows = list(res.data or [])
    except Exception as e:
        return {"error": f"tss_history_query_failed: {e}"}

    series = [
        {
            "date": r.get("date"),
            "daily_tss": r.get("daily_tss"),
            "ctl": r.get("ctl"),
            "atl": r.get("atl"),
            "tsb": r.get("tsb"),
        }
        for r in rows
    ]
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(series),
        "series": series,
    }


def get_biometrics_for_dates(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    raw_dates = args.get("dates")
    if not isinstance(raw_dates, list) or not raw_dates:
        return {"error": "dates array is required"}
    if len(raw_dates) > BIOMETRICS_DATES_MAX:
        return {"error": f"max {BIOMETRICS_DATES_MAX} dates per request"}

    try:
        dates = [parse_coach_date(str(d)) for d in raw_dates]
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    iso_dates = [d.isoformat() for d in dates]
    try:
        res = (
            db.table("biometrics")
            .select(
                "date,hrv_rmssd,resting_hr,spo2_pct,sleep_duration_min,sleep_score,"
                "recovery_score,readiness_score,strain_score"
            )
            .eq("athlete_id", athlete_id)
            .in_("date", iso_dates)
            .order("date")
            .execute()
        )
        rows = list(res.data or [])
    except Exception as e:
        return {"error": f"biometrics_query_failed: {e}"}

    by_date = {str(r.get("date"))[:10]: r for r in rows}
    out_rows: list[dict[str, Any]] = []
    for d in iso_dates:
        row = by_date.get(d)
        if row:
            out_rows.append(
                {
                    "date": d,
                    "hrv_rmssd": row.get("hrv_rmssd"),
                    "resting_hr": row.get("resting_hr"),
                    "spo2_pct": row.get("spo2_pct"),
                    "sleep_duration_min": row.get("sleep_duration_min"),
                    "sleep_score": row.get("sleep_score"),
                    "recovery_score": row.get("recovery_score"),
                    "readiness_score": row.get("readiness_score"),
                    "strain_score": row.get("strain_score"),
                }
            )
        else:
            out_rows.append({"date": d, "available": False})

    return {"count": len(out_rows), "days": out_rows}


def summarize_workouts(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if args.get("period"):
            start, end = _period_bounds(db, athlete_id, str(args["period"]))
        else:
            start, end = _resolve_date_range(db, athlete_id, args, default_days_back=6)
    except ValueError as e:
        return {"error": str(e)}

    rows = query_workouts(
        db,
        athlete_id,
        start_date=start,
        end_date=end,
        sport=str(args["sport"]) if args.get("sport") else None,
        limit=SUMMARIZE_WORKOUTS_MAX,
    )

    total_tss = 0.0
    total_min = 0.0
    sport_mix: dict[str, int] = {}
    hardest: dict[str, Any] | None = None
    hardest_tss = -1.0

    for row in rows:
        tss = float(row.get("tss") or 0)
        total_tss += tss
        dur = _duration_secs(row) or 0
        total_min += dur / 60.0
        sport = str(row.get("sport") or "other")
        sport_mix[sport] = sport_mix.get(sport, 0) + 1
        if tss > hardest_tss:
            hardest_tss = tss
            hardest = _compact_list_row(row)

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "workout_count": len(rows),
        "total_tss": round(total_tss, 1),
        "total_hours": round(total_min / 60.0, 2),
        "sport_mix": sport_mix,
        "hardest_session": hardest,
    }


def _numeric_delta(a: Any, b: Any) -> float | None:
    try:
        if a is None or b is None:
            return None
        return round(float(b) - float(a), 2)
    except (TypeError, ValueError):
        return None


def compare_workouts(db: Client, athlete_id: str, args: dict[str, Any]) -> dict[str, Any]:
    id_a = args.get("workout_id_a") or args.get("workout_id")
    id_b = args.get("workout_id_b")
    if not id_a or not id_b:
        return {"error": "workout_id_a and workout_id_b are required"}

    row_a = fetch_workout_by_id(db, athlete_id, str(id_a))
    row_b = fetch_workout_by_id(db, athlete_id, str(id_b))
    if not row_a or not row_b:
        return {"error": "workout_not_found"}

    summary_a = format_workout_summary(row_a)
    summary_b = format_workout_summary(row_b)
    same_sport = summary_a.get("sport") == summary_b.get("sport")

    deltas = {
        "duration_min": _numeric_delta(summary_a.get("duration_min"), summary_b.get("duration_min")),
        "tss": _numeric_delta(summary_a.get("tss"), summary_b.get("tss")),
        "strain_score": _numeric_delta(summary_a.get("strain_score"), summary_b.get("strain_score")),
        "avg_hr": _numeric_delta(summary_a.get("avg_hr"), summary_b.get("avg_hr")),
        "avg_power_w": _numeric_delta(summary_a.get("avg_power_w"), summary_b.get("avg_power_w")),
        "distance_km": _numeric_delta(summary_a.get("distance_km"), summary_b.get("distance_km")),
    }

    return {
        "workout_a": summary_a,
        "workout_b": summary_b,
        "same_sport": same_sport,
        "deltas_b_minus_a": deltas,
    }

