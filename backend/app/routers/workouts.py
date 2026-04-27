from fastapi import APIRouter, HTTPException
from app.models.schemas import WorkoutPayload
from app.services.algorithms import calculate_cycling_tss

# Create a router instance
router = APIRouter(prefix="/v1/workouts", tags=["Workouts"])

@router.post("/calculate-tss")
async def process_workout(payload: WorkoutPayload):
    """
    Ingests a workout payload, calculates the TSS, and returns the result.
    (In the next step, we will also save this to Supabase).
    """
    
    if payload.workout_type.lower() == "cycling":
        if not payload.normalized_power:
            raise HTTPException(status_code=400, detail="Normalized power is required for cycling TSS.")
            
        # Run the math from your algorithms service
        tss = calculate_cycling_tss(
            duration_seconds=payload.duration_seconds,
            normalized_power=payload.normalized_power,
            ftp=payload.ftp_at_time
        )
        
        return {
            "status": "success",
            "message": "Workout processed",
            "data": {
                "duration_seconds": payload.duration_seconds,
                "calculated_tss": tss
            }
        }
        
    else:
        raise HTTPException(
            status_code=400, 
            detail=f"TSS calculation for {payload.workout_type} is not yet implemented."
        )