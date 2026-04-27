from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Optional
from datetime import date, timedelta
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_biometrics
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
    
    bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).order("date").execute()
    
    hrv_data = []
    sleep_data = []
    series = []

    for row in bio_res.data:
        if row.get("hrv_rmssd"):
            hrv_data.append(row["hrv_rmssd"])
        if row.get("sleep_duration_min"):
            sleep_data.append(row["sleep_duration_min"] / 60.0)
        series.append(row)

    return {
        "hrvData": hrv_data,
        "sleepData": sleep_data,
        "series": series
    }

@router.post("/daily")
async def ingest_daily_biometrics(
    payload: DailyBiometrics,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_db)
):
    """Ingest a daily biometric summary and calculate recovery score in the background."""
    background_tasks.add_task(process_and_save_biometrics, payload, athlete_id, db)
    return {"status": "success", "message": "Biometrics recorded and recovery analysis queued", "date": payload.date}