from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.models.workout import WorkoutPayload
from app.services.algorithms import compute_tss_power
from app.services.processing import process_and_save_workout
from app.dependencies import get_current_athlete, get_user_db
from datetime import datetime, timezone

router = APIRouter(prefix="/v1/workouts", tags=["Workouts"])

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

@router.get("")
async def get_workouts(
    limit: int = 20,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Fetch past workouts for the training history tab."""
    res = db.table("workouts").select("*").eq("athlete_id", athlete_id).order("started_at", desc=True).limit(limit).execute()
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