from datetime import date, timedelta
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.algorithms import calculate_cycling_tss, calculate_training_load, calculate_recovery_score

def process_and_save_workout(payload: WorkoutPayload, athlete_id: str, db):
    # 1. Calculate TSS
    tss = 0.0
    if payload.workout_type.lower() == "cycling" and payload.normalized_power:
        tss = calculate_cycling_tss(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
    elif payload.tss:
        tss = payload.tss

    # 2. Save the workout
    db.table("workouts").upsert({
        "athlete_id": athlete_id,
        "source": payload.source,
        "external_id": payload.external_id,
        "sport": payload.workout_type,
        "started_at": payload.start_time.isoformat(),
        "duration_secs": payload.duration_seconds,
        "tss": tss
    }).execute()

    # 3. Recalculate Training Load (CTL, ATL, TSB)
    start_date = (date.today() - timedelta(days=90)).isoformat()
    history_res = db.table("tss_history").select("date, daily_tss") \
        .eq("athlete_id", athlete_id) \
        .gte("date", start_date).order("date").execute()
    
    daily_map = {row["date"]: row["daily_tss"] for row in history_res.data}
    today_str = date.today().isoformat()
    daily_map[today_str] = daily_map.get(today_str, 0.0) + tss
    
    sorted_dates = sorted(daily_map.keys())
    tss_values = [daily_map[d] for d in sorted_dates]
    
    load_metrics = calculate_training_load(tss_values)
    db.table("tss_history").upsert({
        "athlete_id": athlete_id,
        "date": today_str,
        "daily_tss": daily_map[today_str],
        "ctl": load_metrics["ctl"],
        "atl": load_metrics["atl"],
        "tsb": load_metrics["tsb"]
    }).execute()

def process_and_save_biometrics(payload: DailyBiometrics, athlete_id: str, db):
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
