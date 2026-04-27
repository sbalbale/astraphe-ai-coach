from fastapi import APIRouter, HTTPException, Depends
from app.models.workout import WorkoutPayload
from app.services.algorithms import calculate_cycling_tss
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/workouts", tags=["Workouts"])

@router.post("")
async def ingest_workout(payload: WorkoutPayload, athlete_id: str = Depends(get_current_athlete), db = Depends(get_db)):
    """Ingest a new workout"""
    # Calculation & persistence logic goes here
    return {"id": "uuid-placeholder", "tss": 38.2, "if_value": 0.71, "message": "Workout ingested."}

@router.post("/calculate-tss")
async def process_workout(payload: WorkoutPayload):
    if payload.workout_type.lower() == "cycling":
        if not payload.normalized_power:
            raise HTTPException(status_code=400, detail="Normalized power is required for cycling TSS.")
        tss = calculate_cycling_tss(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
        return {"status": "success", "message": "Workout processed", "data": {"calculated_tss": tss}}
    raise HTTPException(status_code=400, detail="Not implemented.")