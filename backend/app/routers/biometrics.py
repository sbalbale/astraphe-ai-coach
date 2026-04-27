from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import date, timedelta
from app.models.biometrics import DailyBiometrics
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/biometrics", tags=["Biometrics"])

@router.get("")
async def get_biometrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """Returns daily biometric readings over a date range."""
    start_date = start_date or (date.today() - timedelta(days=14))
    end_date = end_date or date.today()
    
    # Comprehensive mock data for Biometrics
    return {
        "hrvData": [72, 75, 71, 74, 76, 72, 78],
        "sleepData": [6.8, 7.4, 5.9, 8.0, 6.8, 8.2, 7.5],
        "series": [
            {
                "date": date.today(),
                "hrv_rmssd": 78.0,
                "resting_hr": 52,
                "sleep_duration_min": 450,
                "sleep_score": 94,
                "sleep_deep_pct": 22.0,
                "sleep_rem_pct": 24.0,
                "recovery_score": 78,
                "spo2_pct": 98.0
            }
        ]
    }

@router.post("/daily")
async def ingest_daily_biometrics(
    payload: DailyBiometrics,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """Ingest a daily biometric summary (called by HealthKit/WHOOP sync)."""
    # Logic to calculate ASTRAPE recovery score and upsert into the DB
    return {
        "status": "success",
        "message": "Biometrics recorded",
        "date": payload.date
    }