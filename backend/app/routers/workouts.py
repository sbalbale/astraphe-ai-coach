from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.models.workout import WorkoutPayload
from app.services.algorithms import calculate_cycling_tss
from app.services.processing import process_and_save_workout
from app.dependencies import get_current_athlete, get_user_db

router = APIRouter(prefix="/v1/workouts", tags=["Workouts"])

@router.get("")
async def get_workouts(
    limit: int = 20,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Fetch past workouts for the training history tab."""
    res = db.table("workouts").select("*").eq("athlete_id", athlete_id).order("started_at", desc=True).limit(limit).execute()
    return res.data

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

@router.post("/calculate-tss")
async def process_workout(payload: WorkoutPayload):
    if payload.workout_type.lower() == "cycling":
        if not payload.normalized_power:
            raise HTTPException(status_code=400, detail="Normalized power is required for cycling TSS.")
        tss = calculate_cycling_tss(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
        return {"status": "success", "message": "Workout processed", "data": {"calculated_tss": tss}}
    raise HTTPException(status_code=400, detail="Not implemented.")