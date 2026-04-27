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
    
    # Comprehensive mock data for the Plan screen
    return {
        "workouts": [
            {"type": "Run", "title": "Easy Recovery Run", "date": "Today", "duration": "45m", "load": 38},
            {"type": "Bike", "title": "Long Endurance Ride", "date": "Yesterday", "duration": "3h 15m", "load": 142},
            {"type": "Strength", "title": "Lower Body / Core", "date": "Wed", "duration": "45m", "load": 22},
            {"type": "Run", "title": "Threshold Intervals", "date": "Tue", "duration": "1h 10m", "load": 85}
        ],
        "plan": {
            "20": {"type": "Run", "title": "Easy Run", "duration": "45 min", "tss": 38, "status": "done", "note": "Aerobic base. Keep HR in Z2."},
            "21": {"type": "Bike", "title": "Threshold Intervals", "duration": "90 min", "tss": 95, "status": "done", "note": "5x8min @FTP. 3min recovery."},
            "22": {"type": "Rest", "title": "Rest Day", "duration": "-", "tss": 0, "status": "done", "note": "Full recovery. Walk if you want."},
            "23": {"type": "Run", "title": "Tempo Run", "duration": "55 min", "tss": 68, "status": "done", "note": "20min tempo in Z3-Z4."},
            "24": {"type": "Run", "title": "Long Run", "duration": "2h 15m", "tss": 80, "status": "done", "note": "Steady Z2. Last 20min at marathon pace."},
            "25": {"type": "Bike", "title": "Long Ride", "duration": "3h", "tss": 95, "status": "done", "note": "Endurance Z2. High cadence focus."},
            "26": {"type": "Rest", "title": "Recovery", "duration": "30 min", "tss": 18, "status": "today", "note": "Optional easy swim or walk."},
            "27": {"type": "Run", "title": "VO2max Intervals", "duration": "65 min", "tss": 85, "status": "planned", "note": "5x4min @95% FTP / Z5 HR. ASTRAPE recommended."},
            "28": {"type": "Bike", "title": "Endurance Ride", "duration": "2h", "tss": 60, "status": "planned", "note": "Z2 only. Keep HR below 145."},
            "29": {"type": "Run", "title": "Easy Run", "duration": "40 min", "tss": 35, "status": "planned", "note": "Pure aerobic. No watch pressure."},
            "30": {"type": "Strength", "title": "Strength & Core", "duration": "50 min", "tss": 40, "status": "planned", "note": "Gym. Focus on glutes and hip stability."}
        }
    }