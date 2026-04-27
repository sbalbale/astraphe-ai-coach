from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Optional
from datetime import date, timedelta
from app.models.biometrics import DailyBiometrics
from app.services.algorithms import calculate_recovery_score
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/biometrics", tags=["Biometrics"])

def process_and_save_biometrics(payload: DailyBiometrics, athlete_id: str, db):
    # Fetch baseline metrics from athletes table or use defaults
    # In a real app, we'd have a rolling baseline calculation
    athlete_res = db.table("athletes").select("hrv_baseline, rhr_baseline").eq("id", athlete_id).single().execute()
    baseline_hrv = athlete_res.data.get("hrv_baseline") or 65.0
    baseline_rhr = athlete_res.data.get("rhr_baseline") or 50
    
    recovery_score = calculate_recovery_score(
        hrv=payload.hrv_rmssd or 0.0,
        baseline_hrv=baseline_hrv,
        sleep_score=payload.sleep_score or 0,
        resting_hr=payload.resting_hr or 0,
        baseline_rhr=baseline_rhr
    )
    
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "hrv_rmssd": payload.hrv_rmssd,
        "resting_hr": payload.resting_hr,
        "sleep_duration_min": payload.sleep_duration_min,
        "sleep_score": payload.sleep_score,
        "recovery_score": recovery_score,
        "hrv_source": payload.source
    }).execute()

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