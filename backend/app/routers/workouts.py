from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from app.models.workout import WorkoutPayload, WorkoutUpdatePayload
from app.services.algorithms import compute_tss_power
from app.services.processing import (
    _refresh_daily_strain_for_day_sync,
    normalize_sport,
    process_and_save_workout,
    recalculate_tss_history,
)
from app.dependencies import get_current_athlete, get_user_db
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/v1/workouts", tags=["Workouts"])

_WORKOUT_LIST_COLUMNS = (
    "id, athlete_id, source, sport, title, started_at, ended_at, duration_seconds, "
    "distance_m, avg_hr, max_hr, avg_power_w, norm_power_w, avg_pace_sec_km, tss, "
    "strain_score, strava_activity_id, strava_streams_fetched, intervals_source, "
    "hr_zone_0_pct, hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, "
    "hr_zone_5_pct, elevation_gain_m, primary_source, source_ids"
)

def _parse_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    # Supabase returns ISO strings
    if isinstance(v, str):
        try:
            # Accept "Z"
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
        except Exception:
            return None
    return None

def _duration_secs(row: dict) -> int | None:
    """
    Compute duration in seconds from the most reliable available fields.
    Preference order:
    - explicit duration fields (if present)
    - ended_at - started_at
    """
    for k in ("duration_secs", "duration_seconds"):
        if k in row and row.get(k) is not None:
            try:
                val = int(row.get(k))
                if val >= 0:
                    return val
            except Exception:
                pass
    start = _parse_dt(row.get("started_at"))
    end = _parse_dt(row.get("ended_at"))
    if start and end:
        # Ensure both aware/naive match
        if start.tzinfo is None and end.tzinfo is not None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None and start.tzinfo is not None:
            end = end.replace(tzinfo=timezone.utc)
        secs = int((end - start).total_seconds())
        return max(0, secs)
    return None

def _iso_or_none(v: datetime | None) -> str | None:
    return v.isoformat() if v else None

def _clean_optional_title(v: str | None) -> str | None:
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None

def _workout_update_data(payload: WorkoutUpdatePayload, existing: dict) -> dict:
    fields = payload.model_fields_set
    update_data: dict = {}

    if "workout_type" in fields:
        if not payload.workout_type:
            raise HTTPException(status_code=400, detail="sport is required when provided")
        update_data["sport"] = normalize_sport(payload.workout_type)

    if "title" in fields:
        update_data["title"] = _clean_optional_title(payload.title)

    scalar_fields = {
        "distance_m": "distance_m",
        "average_power": "avg_power_w",
        "normalized_power": "norm_power_w",
        "average_hr": "avg_hr",
        "max_hr": "max_hr",
        "avg_pace_sec_km": "avg_pace_sec_km",
        "tss": "tss",
        "hr_zone_0_pct": "hr_zone_0_pct",
        "hr_zone_1_pct": "hr_zone_1_pct",
        "hr_zone_2_pct": "hr_zone_2_pct",
        "hr_zone_3_pct": "hr_zone_3_pct",
        "hr_zone_4_pct": "hr_zone_4_pct",
        "hr_zone_5_pct": "hr_zone_5_pct",
    }
    for field_name, column_name in scalar_fields.items():
        if field_name in fields:
            update_data[column_name] = getattr(payload, field_name)

    start = payload.start_time if "start_time" in fields else _parse_dt(existing.get("started_at"))
    ended = payload.ended_at if "ended_at" in fields else _parse_dt(existing.get("ended_at"))
    duration = payload.duration_seconds if "duration_seconds" in fields else _duration_secs(existing)

    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="duration_seconds must be an integer")
        if duration < 0:
            raise HTTPException(status_code=400, detail="duration_seconds cannot be negative")

    if "start_time" in fields:
        if start is None:
            raise HTTPException(status_code=400, detail="started_at is invalid")
        update_data["started_at"] = _iso_or_none(start)

    if "duration_seconds" in fields:
        update_data["duration_seconds"] = duration

    if "ended_at" in fields:
        update_data["ended_at"] = _iso_or_none(ended)

    if (("start_time" in fields) or ("duration_seconds" in fields)) and start and duration is not None:
        ended = start + timedelta(seconds=duration)
        update_data["ended_at"] = ended.isoformat()
    elif (("start_time" in fields) or ("ended_at" in fields)) and start and ended:
        update_data["duration_seconds"] = max(0, int((ended - start).total_seconds()))

    return update_data

def _patch_refresh_days(existing: dict, updated: dict) -> set:
    days = set()
    for row in (existing, updated):
        started = _parse_dt(row.get("started_at"))
        if started:
            days.add(started.date())
    return days

@router.get("")
def get_workouts(
    limit: int = Query(20, ge=1, le=200),
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Fetch past workouts for the training history tab."""
    res = (
        db.table("workouts")
        .select(_WORKOUT_LIST_COLUMNS)
        .eq("athlete_id", athlete_id)
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    # Add a computed duration_secs for the mobile app + any clients expecting it.
    for r in rows:
        d = _duration_secs(r)
        if d is not None:
            r["duration_secs"] = d
    return rows

@router.post("")
async def ingest_workout(
    payload: WorkoutPayload, 
    background_tasks: BackgroundTasks, 
    athlete_id: str = Depends(get_current_athlete), 
    db = Depends(get_user_db)
):
    """Ingest a new workout and calculate analysis in the background."""
    background_tasks.add_task(process_and_save_workout, payload, athlete_id, db)
    return {"status": "success", "message": "Workout ingestion and analysis queued."}

@router.patch("/{workout_id}")
async def update_workout(
    workout_id: str,
    payload: WorkoutUpdatePayload,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    """
    Update editable scalar fields for an existing workout.

    Integration identity, raw payloads, streams, laps, and source bookkeeping are intentionally
    not patchable here so imported activity detail remains attached to the workout.
    """
    try:
        existing_res = (
            db.table("workouts")
            .select("*")
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
        )
        existing = existing_res.data if existing_res else None
        if not existing:
            raise HTTPException(status_code=404, detail="Workout not found")

        update_data = _workout_update_data(payload, existing)
        if not update_data:
            raise HTTPException(status_code=400, detail="No editable workout fields provided")

        updated_res = (
            db.table("workouts")
            .update(update_data)
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        updated = (updated_res.data or [None])[0] if updated_res else None
        if not updated:
            refetch = (
                db.table("workouts")
                .select("*")
                .eq("id", workout_id)
                .eq("athlete_id", athlete_id)
                .maybe_single()
                .execute()
            )
            updated = refetch.data if refetch else None
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update workout")

        duration = _duration_secs(updated)
        if duration is not None:
            updated["duration_secs"] = duration

        background_tasks.add_task(recalculate_tss_history, athlete_id, db)
        for day in _patch_refresh_days(existing, updated):
            background_tasks.add_task(_refresh_daily_strain_for_day_sync, db, athlete_id, day)

        return {"status": "success", "workout": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update workout: {str(e)}")

@router.delete("/{workout_id}")
async def delete_workout(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    """
    Delete a workout by its UUID id.
    RLS policy will also enforce athlete scoping via the user's JWT.
    """
    try:
        existing = (
            db.table("workouts")
            .select("id")
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Workout not found")

        db.table("workouts").delete().eq("id", workout_id).eq("athlete_id", athlete_id).execute()
        return {"status": "success", "deleted_id": workout_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete workout: {str(e)}")

@router.post("/calculate-tss")
async def process_workout(
    payload: WorkoutPayload,
    athlete_id: str = Depends(get_current_athlete),
):
    if payload.workout_type.lower() == "cycling":
        if not payload.normalized_power:
            raise HTTPException(status_code=400, detail="Normalized power is required for cycling TSS.")
        tss = compute_tss_power(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
        return {"status": "success", "message": "Workout processed", "data": {"calculated_tss": tss}}
    raise HTTPException(status_code=400, detail="Not implemented.")