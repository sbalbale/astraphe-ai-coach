from datetime import date, timedelta
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.algorithms import (
    calculate_cycling_tss, 
    calculate_training_load, 
    calculate_astrape_recovery_score, 
    calculate_astrape_sleep_score,
    calculate_astrape_sleep_need,
    normalize_rowing_watts
)

def process_and_save_workout(payload: WorkoutPayload, athlete_id: str, db):
    # 1. Calculate TSS
    tss = 0.0
    sport = payload.workout_type.lower()
    
    # Check if we have HR zone data
    hr_zones = {
        1: payload.hr_zone_1_pct,
        2: payload.hr_zone_2_pct,
        3: payload.hr_zone_3_pct,
        4: payload.hr_zone_4_pct,
        5: payload.hr_zone_5_pct
    }
    has_hr_zones = any(v is not None for v in hr_zones.values())

    if sport == "cycling" and payload.normalized_power:
        tss = calculate_cycling_tss(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
    elif has_hr_zones and payload.duration_seconds:
        # Use HR zones for TSS if available (standard for Run/Strength/Rowing when power is missing)
        from app.services.algorithms import calculate_hr_tss
        tss = calculate_hr_tss(payload.duration_seconds, hr_zones)
    elif sport == "rowing" and hasattr(payload, 'avg_power') and payload.avg_power:
        # Fallback for rowing if HR zones missing
        norm_watts = normalize_rowing_watts(payload.avg_power)
        tss = calculate_cycling_tss(payload.duration_seconds, int(norm_watts), payload.ftp_at_time)
    elif payload.tss:
        tss = payload.tss
    
    # Map sport to internal enums if needed
    mapped_sport = sport if sport in ('run', 'bike', 'swim', 'strength', 'rowing') else 'other'
    if sport == 'cycling': mapped_sport = 'bike'

    # 2. Save the workout
    db.table("workouts").upsert({
        "athlete_id": athlete_id,
        "source": payload.source,
        "external_id": payload.external_id,
        "sport": mapped_sport,
        "started_at": payload.start_time.isoformat(),
        "duration_secs": payload.duration_seconds,
        "tss": tss,
        "hr_zone_1_pct": payload.hr_zone_1_pct,
        "hr_zone_2_pct": payload.hr_zone_2_pct,
        "hr_zone_3_pct": payload.hr_zone_3_pct,
        "hr_zone_4_pct": payload.hr_zone_4_pct,
        "hr_zone_5_pct": payload.hr_zone_5_pct
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
    # 1. Get previous day's debt and strain to calculate current need
    prev_date = payload.date - timedelta(days=1)
    prev_res = db.table("biometrics").select("sleep_debt_min, day_strain").eq("athlete_id", athlete_id).eq("date", prev_date.isoformat()).maybe_single().execute()
    
    prev_debt = 0
    prev_strain = 0
    if prev_res.data:
        prev_debt = prev_res.data.get("sleep_debt_min") or 0
        prev_strain = prev_res.data.get("day_strain") or 0
        
    athlete_res = db.table("athletes").select("hrv_baseline, rhr_baseline").eq("id", athlete_id).single().execute()
    baseline_hrv = athlete_res.data.get("hrv_baseline") or 65.0
    baseline_rhr = athlete_res.data.get("rhr_baseline") or 50
    
    # 2. Calculate current need based on yesterday's activity and accumulated debt
    astrape_need = calculate_astrape_sleep_need(480, prev_strain, prev_debt)
    
    astrape_sleep = calculate_astrape_sleep_score(
        duration_min=payload.sleep_duration_min or 0.0,
        sleep_need_min=astrape_need,
        rem_pct=payload.sleep_rem_pct or 0.0,
        deep_pct=payload.sleep_deep_pct or 0.0
    )

    # 3. Calculate rolling debt for NEXT night (cap at 120m)
    current_actual = payload.sleep_duration_min or 0
    next_night_debt = min(120, max(0, astrape_need - current_actual))

    astrape_recovery = calculate_astrape_recovery_score(
        hrv=payload.hrv_rmssd or 0.0,
        baseline_hrv=baseline_hrv,
        sleep_score=astrape_sleep,
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
        "sleep_need_min": astrape_need,
        "sleep_debt_min": next_night_debt, # We store the debt this day created for tomorrow
        "astrape_sleep_score": astrape_sleep,
        "astrape_recovery_score": astrape_recovery,
        "hrv_source": payload.source,
        "sleep_deep_pct": payload.sleep_deep_pct,
        "sleep_rem_pct": payload.sleep_rem_pct,
        "skin_temp_deviation": payload.skin_temp_deviation,
        "spo2_pct": payload.spo2_pct,
        "day_strain": payload.day_strain # We should add this to the model
    }).execute()
