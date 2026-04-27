from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import date, timedelta
from typing import Optional, List
from app.models.athlete import AthleteState, AthleteProfileUpdate
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/athlete", tags=["Athlete"])

@router.post("/onboard")
async def onboard_athlete(athlete_id: str = Depends(get_current_athlete), db = Depends(get_db)):
    """Seeds initial sample data for a newly registered athlete."""
    today = date.today()
    
    # Seed 7 days of TSS history
    tss_entries = [
        {"athlete_id": athlete_id, "date": (today - timedelta(days=6)).isoformat(), "daily_tss": 61, "ctl": 61, "atl": 55, "tsb": 6},
        {"athlete_id": athlete_id, "date": (today - timedelta(days=5)).isoformat(), "daily_tss": 72, "ctl": 62, "atl": 65, "tsb": -3},
        {"athlete_id": athlete_id, "date": (today - timedelta(days=4)).isoformat(), "daily_tss": 55, "ctl": 62, "atl": 58, "tsb": 4},
        {"athlete_id": athlete_id, "date": (today - timedelta(days=3)).isoformat(), "daily_tss": 88, "ctl": 64, "atl": 72, "tsb": -8},
        {"athlete_id": athlete_id, "date": (today - timedelta(days=2)).isoformat(), "daily_tss": 110, "ctl": 65, "atl": 88, "tsb": -23},
        {"athlete_id": athlete_id, "date": (today - timedelta(days=1)).isoformat(), "daily_tss": 130, "ctl": 67, "atl": 95, "tsb": -28},
        {"athlete_id": athlete_id, "date": today.isoformat(), "daily_tss": 0, "ctl": 68, "atl": 38, "tsb": 28},
    ]
    db.table("tss_history").upsert(tss_entries).execute()
    
    # Seed today's biometrics
    db.table("biometrics").upsert([{
        "athlete_id": athlete_id,
        "date": today.isoformat(),
        "hrv_rmssd": 78.0,
        "resting_hr": 52,
        "sleep_duration_min": 450,
        "sleep_score": 94,
        "recovery_score": 78,
        "spo2_pct": 98.0
    }]).execute()
    
    # Seed upcoming training plan
    plan_entries = [
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=1)).isoformat(), "sport": "Run", "title": "Easy Recovery Run", "description": "Aerobic base. Keep HR in Z2.", "duration_min": 45, "target_tss": 38, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=2)).isoformat(), "sport": "Bike", "title": "Threshold Intervals", "description": "5x8min @FTP. 3min recovery.", "duration_min": 90, "target_tss": 95, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=3)).isoformat(), "sport": "Run", "title": "Rest Day", "description": "Full recovery. Optional walk.", "duration_min": 0, "target_tss": 0, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=4)).isoformat(), "sport": "Run", "title": "Tempo Run", "description": "20min tempo in Z3-Z4.", "duration_min": 55, "target_tss": 68, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=5)).isoformat(), "sport": "Bike", "title": "Long Endurance Ride", "description": "Z2 only. High cadence focus.", "duration_min": 180, "target_tss": 95, "status": "planned"},
    ]
    db.table("training_plans").upsert(plan_entries).execute()
    
    return {"status": "success", "message": "Athlete onboarded with sample data"}



@router.get("/state", response_model=AthleteState)
async def get_athlete_state(athlete_id: str = Depends(get_current_athlete), db = Depends(get_db)):
    """
    Returns the athlete's current physiological state including computed CTL, ATL, TSB, and readiness score.
    """
    # Fetch athlete
    athlete_res = db.table("athletes").select("display_name").eq("id", athlete_id).execute()
    if not athlete_res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")
    display_name = athlete_res.data[0]["display_name"]
    
    # Fetch latest tss_history
    tss_res = db.table("tss_history").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    ctl, atl, tsb = 0.0, 0.0, 0.0
    if tss_res.data:
        tss = tss_res.data[0]
        ctl = tss.get("ctl") or 0.0
        atl = tss.get("atl") or 0.0
        tsb = tss.get("tsb") or 0.0

    # Fetch latest biometrics
    bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    bio = bio_res.data[0] if bio_res.data else {}

    return {
        "athlete_id": athlete_id,
        "display_name": display_name,
        "date": date.today(),
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "hrv_rmssd": bio.get("hrv_rmssd"),
        "hrv_delta_7d": 0.0, # Placeholder
        "resting_hr": bio.get("resting_hr"),
        "sleep_hours": bio.get("sleep_duration_min", 0) / 60.0 if bio.get("sleep_duration_min") else None,
        "sleep_score": bio.get("sleep_score"),
        "recovery_score": bio.get("recovery_score"),
        "readiness_score": bio.get("recovery_score", 0) or 0,
        "readiness_label": "Optimal" if (bio.get("recovery_score", 0) or 0) > 70 else "Moderate",
        "readiness_recommendation": "Data pulled from database."
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
    
    # Query recent tss_history
    tss_res = db.table("tss_history").select("date,ctl,atl,tsb").eq("athlete_id", athlete_id).gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).order("date").execute()
    
    training_load_data = []
    for row in tss_res.data:
        d = date.fromisoformat(row["date"])
        training_load_data.append({
            "date": d.strftime("%a"),
            "ctl": row["ctl"] or 0,
            "atl": row["atl"] or 0,
            "tsb": row["tsb"] or 0
        })

    return {
        "athlete_id": athlete_id,
        "start_date": start_date,
        "end_date": end_date,
        "trainingLoadData": training_load_data,
        "paceData": [],
        "zoneData": []
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

    response = db.table("athletes").update(update_data).eq("id", athlete_id).execute()
    
    return {"status": "success", "message": "Profile updated successfully", "updated_fields": update_data}