from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import date, timedelta
from typing import Optional, List
from app.models.athlete import AthleteState, AthleteProfileUpdate
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/athlete", tags=["Athlete"])

@router.get("/state", response_model=AthleteState)
async def get_athlete_state(athlete_id: str = Depends(get_current_athlete), db = Depends(get_db)):
    """
    Returns the athlete's current physiological state including computed CTL, ATL, TSB, and readiness score.
    """
    # In a real implementation, this queries the `tss_history` and `biometrics` tables via Supabase
    # Placeholder returning the expected schema
    return {
        "athlete_id": athlete_id,
        "display_name": "Marcus Jensen",
        "date": date.today(),
        "ctl": 68.4,
        "atl": 38.1,
        "tsb": 28.2,
        "hrv_rmssd": 78.0,
        "hrv_delta_7d": 6.3,
        "resting_hr": 52,
        "sleep_hours": 7.5,
        "sleep_score": 94,
        "recovery_score": 78,
        "readiness_score": 78,
        "readiness_label": "Optimal",
        "readiness_recommendation": "High HRV and positive TSB — strong window for a quality effort today."
    }

@router.get("/metrics")
async def get_athlete_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    metrics: str = Query("ctl,atl,tsb", description="Comma-separated metrics to include"),
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """Returns computed metrics over a date range."""
    start_date = start_date or (date.today() - timedelta(days=42))
    end_date = end_date or date.today()
    
    # Comprehensive mock data for the Training screen
    return {
        "athlete_id": athlete_id,
        "start_date": start_date,
        "end_date": end_date,
        "trainingLoadData": [
            {"date": "Mon", "ctl": 61, "atl": 55, "tsb": +6},
            {"date": "Tue", "ctl": 62, "atl": 65, "tsb": -3},
            {"date": "Wed", "ctl": 62, "atl": 58, "tsb": +4},
            {"date": "Thu", "ctl": 64, "atl": 72, "tsb": -8},
            {"date": "Fri", "ctl": 65, "atl": 88, "tsb": -23},
            {"date": "Sat", "ctl": 67, "atl": 95, "tsb": -28},
            {"date": "Sun", "ctl": 68, "atl": 38, "tsb": +28}
        ],
        "paceData": [
            {"dist": 0, "pace": 5.42},
            {"dist": 2, "pace": 5.40},
            {"dist": 4, "pace": 5.38},
            {"dist": 6, "pace": 5.41},
            {"dist": 8, "pace": 5.35},
            {"dist": 10, "pace": 5.32}
        ],
        "zoneData": [
            {"zone": "Z1 Recovery", "pct": 18, "color": "#4621FF"},
            {"zone": "Z2 Aerobic", "pct": 42, "color": "#00C8A8"},
            {"zone": "Z3 Tempo", "pct": 22, "color": "#FFCB88"},
            {"zone": "Z4 Threshold", "pct": 13, "color": "#F07178"},
            {"zone": "Z5 VO2max", "pct": 5, "color": "#FF4791"}
        ]
    }

@router.patch("/profile")
async def update_athlete_profile(
    payload: AthleteProfileUpdate,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """
    Update athlete physiological anchors (e.g., FTP, max HR).
    Should trigger async recalculation of historical TSS if FTP changes.
    """
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    # DB update logic here
    # response = db.table("athletes").update(update_data).eq("id", athlete_id).execute()
    
    return {"status": "success", "message": "Profile updated successfully", "updated_fields": update_data}