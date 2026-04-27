from fastapi import APIRouter, Depends
from typing import Optional
from datetime import date, timedelta
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/plan", tags=["Training Plan"])

@router.get("")
async def get_training_plan(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """Returns the athlete's training plan for a date range."""
    start_date = start_date or date.today()
    end_date = end_date or (date.today() + timedelta(days=7))
    
    # Placeholder querying the `training_plans` table
    return {
        "plan": [
            {
                "id": "placeholder-uuid",
                "planned_date": start_date,
                "sport": "run",
                "title": "VO2max Intervals",
                "description": "5×4min @95% FTP with 3min recovery. Warm up 15min, cool down 10min.",
                "duration_min": 65,
                "target_tss": 85,
                "target_zones": {"Z1": 25, "Z2": 0, "Z3": 0, "Z4": 16, "Z5": 24},
                "status": "planned",
                "generated_by": "astrape_ai"
            }
        ]
    }