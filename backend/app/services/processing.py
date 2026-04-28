from datetime import date, timedelta
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics

from app.services.algorithms import (
    calculate_cycling_tss, 
    calculate_hr_tss,
    calculate_training_load, 
    calculate_astrape_sleep_score,
    calculate_astrape_sleep_need,
    normalize_rowing_watts,
    calculate_raw_strain_score,
    calculate_astrape_strain_score,
    calculate_astrape_recovery_score,
    calculate_astrape_readiness_score
)

def process_and_save_workout(payload: WorkoutPayload, athlete_id: str, db):
    # 1. Evaluate Data Sources
    tss = 0.0
    sport = payload.workout_type.lower()
    if sport in ("gym", "strength_training"):
        sport = "strength"
    
    hr_zones = {
        1: payload.hr_zone_1_pct,
        2: payload.hr_zone_2_pct,
        3: payload.hr_zone_3_pct,
        4: payload.hr_zone_4_pct,
        5: payload.hr_zone_5_pct
    }
    has_hr_zones = any(v is not None for v in hr_zones.values())
    hr_zone_0_pct = getattr(payload, "hr_zone_0_pct", None)
    if hr_zone_0_pct is None and has_hr_zones:
        try:
            s = sum(int(v or 0) for v in hr_zones.values())
            hr_zone_0_pct = max(0, 100 - s)
        except Exception:
            hr_zone_0_pct = None

    # 2. Calculate Training Stress Score (TSS)
    if sport == "cycling" and payload.normalized_power:
        tss = calculate_cycling_tss(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
    elif has_hr_zones and payload.duration_seconds:
        # Use HR zones for TSS if available (standard for Run/Strength/Rowing when power is missing)
        tss = calculate_hr_tss(payload.duration_seconds, hr_zones)
    elif sport == "rowing" and hasattr(payload, 'avg_power') and payload.avg_power:
        # Fallback for rowing if HR zones missing
        norm_watts = normalize_rowing_watts(payload.avg_power)
        tss = calculate_cycling_tss(payload.duration_seconds, int(norm_watts), payload.ftp_at_time)
    elif getattr(payload, "tss", None):
        tss = getattr(payload, "tss")
    
    # Map sport to internal enum conventions
    mapped_sport = sport if sport in ('run', 'bike', 'swim', 'strength', 'rowing') else 'other'
    if sport == 'cycling': mapped_sport = 'bike'

    # Duration / end time alignment
    duration_seconds = payload.duration_seconds
    ended_at = payload.ended_at
    if ended_at is None and payload.start_time and duration_seconds:
        ended_at = payload.start_time + timedelta(seconds=duration_seconds)
    if duration_seconds is None and payload.start_time and ended_at:
        duration_seconds = int(max(0, (ended_at - payload.start_time).total_seconds()))

    # 3. Calculate Physiological Cardiovascular Strain (0-100 scale)
    raw_strain = 0.0
    if has_hr_zones and duration_seconds:
        # Convert the None values to 0.0 for safety
        safe_hr_zones = {k: (v or 0.0) for k, v in hr_zones.items()}
        # Get duration in minutes for the specific zones
        zone_minutes = {k: (v / 100.0) * (duration_seconds / 60.0) for k, v in safe_hr_zones.items()}
        raw_strain = calculate_raw_strain_score(zone_minutes)
    
    astrape_strain_score = calculate_astrape_strain_score(raw_strain)

    # 4. Save the workout to Supabase
    db.table("workouts").upsert({
        "athlete_id": athlete_id,
        "source": payload.source,
        "external_id": payload.external_id,
        "sport": mapped_sport,
        "title": getattr(payload, "title", None),
        "started_at": payload.start_time.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "distance_m": payload.distance_m,
        "avg_hr": payload.average_hr,
        "max_hr": payload.max_hr,
        "norm_power_w": payload.normalized_power,
        "avg_pace_sec_km": payload.avg_pace_sec_km,
        "tss": tss,
        "astrape_strain_score": astrape_strain_score,
        "hr_zone_0_pct": hr_zone_0_pct,
        "hr_zone_1_pct": payload.hr_zone_1_pct,
        "hr_zone_2_pct": payload.hr_zone_2_pct,
        "hr_zone_3_pct": payload.hr_zone_3_pct,
        "hr_zone_4_pct": payload.hr_zone_4_pct,
        "hr_zone_5_pct": payload.hr_zone_5_pct
    }).execute()

    # 5. Recalculate Training Load (CTL, ATL, TSB)
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
    # Supabase upsert needs explicit conflict target when the unique constraint
    # isn't the primary key.
    db.table("tss_history").upsert({
        "athlete_id": athlete_id,
        "date": today_str,
        "daily_tss": daily_map[today_str],
        "ctl": load_metrics["ctl"],
        "atl": load_metrics["atl"],
        "tsb": load_metrics["tsb"]
    }, on_conflict="athlete_id,date").execute()


def process_and_save_biometrics(payload: DailyBiometrics, athlete_id: str, db):
    # 1. Fetch Previous Day's Biometrics
    prev_date = payload.date - timedelta(days=1)
    prev_res = db.table("biometrics").select("sleep_debt_min, day_strain").eq("athlete_id", athlete_id).eq("date", prev_date.isoformat()).maybe_single().execute()
    
    prev_debt = 0.0
    prev_strain = 0.0
    if prev_res.data:
        prev_debt = prev_res.data.get("sleep_debt_min") or 0.0
        prev_strain = prev_res.data.get("day_strain") or 0.0
        
    # 2. Fetch Athlete Baselines
    athlete_res = db.table("athletes").select("hrv_baseline, rhr_baseline").eq("id", athlete_id).single().execute()
    baseline_hrv = athlete_res.data.get("hrv_baseline") or 65.0
    baseline_rhr = athlete_res.data.get("rhr_baseline") or 50.0
    
    # 3. Fetch ATL Data for Readiness Modeling
    # We need the prior day's ATL and the 30-day max ATL to compute muscular fatigue
    start_date_30d = (payload.date - timedelta(days=30)).isoformat()
    atl_res = db.table("tss_history").select("atl").eq("athlete_id", athlete_id).gte("date", start_date_30d).order("date").execute()
    
    prior_day_atl = 0.0
    prior_day_atl_max_30d = 1.0 # Default 1 to prevent division by zero
    
    if atl_res.data:
        atls = [row["atl"] for row in atl_res.data if row["atl"] is not None]
        if atls:
            prior_day_atl_max_30d = max(atls) or 1.0
            prior_day_atl = atls[-1]
            
    # 4. Process Sleep Architecture
    astrape_need = calculate_astrape_sleep_need(480, prev_strain, prev_debt)
    
    astrape_sleep = calculate_astrape_sleep_score(
        duration_min=payload.sleep_duration_min or 0.0,
        sleep_need_min=astrape_need,
        rem_pct=payload.sleep_rem_pct or 0.0,
        deep_pct=payload.sleep_deep_pct or 0.0
    )

    current_actual = payload.sleep_duration_min or 0.0
    next_night_debt = min(120, max(0, astrape_need - current_actual))

    # 5. Process Recovery (Autonomic Repair)
    astrape_recovery = calculate_astrape_recovery_score(
        hrv_rmssd=payload.hrv_rmssd or 0.0,
        hrv_baseline_30d=baseline_hrv,
        resting_hr=payload.resting_hr or 0,
        resting_hr_baseline_30d=baseline_rhr,
        sleep_score=astrape_sleep
    )
    
    # 6. Process Readiness (Capacity to Train)
    astrape_readiness = calculate_astrape_readiness_score(
        recovery_score=astrape_recovery,
        prior_day_atl=prior_day_atl,
        prior_day_atl_max_30d=prior_day_atl_max_30d,
        skin_temp_deviation=payload.skin_temp_deviation or 0.0,
        spo2_pct=payload.spo2_pct or 100.0
    )
    
    # 7. Save to Supabase
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "hrv_rmssd": payload.hrv_rmssd,
        "resting_hr": payload.resting_hr,
        "sleep_duration_min": payload.sleep_duration_min,
        "sleep_score": payload.sleep_score,
        "sleep_need_min": astrape_need,
        "sleep_debt_min": next_night_debt,
        "astrape_sleep_score": astrape_sleep,
        "astrape_recovery_score": astrape_recovery,
        "astrape_readiness_score": astrape_readiness,
        "hrv_source": payload.source,
        "sleep_deep_pct": payload.sleep_deep_pct,
        "sleep_rem_pct": payload.sleep_rem_pct,
        "skin_temp_deviation": payload.skin_temp_deviation,
        "spo2_pct": payload.spo2_pct,
        "day_strain": payload.day_strain
    }).execute()