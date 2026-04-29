from datetime import date, timedelta, datetime
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
    calculate_astrape_readiness_score,
    calculate_rhr_baseline,
    calculate_hrv_baseline,
    calculate_weekly_tss_target,
    calculate_threshold_hr_est
)

def recalculate_tss_history(athlete_id: str, db):
    """
    Fetches all workouts for an athlete, aggregates TSS by date,
    and recalculates the entire PMC (CTL/ATL/TSB) history.
    """
    # 1. Fetch all workouts with TSS
    res = db.table("workouts").select("started_at, tss").eq("athlete_id", athlete_id).order("started_at").execute()
    if not res or not res.data:
        return

    # 2. Aggregate TSS by date
    daily_tss = {}
    for w in res.data:
        # Robustly parse date from ISO string (YYYY-MM-DD)
        d = date.fromisoformat(w["started_at"][:10])
        daily_tss[d] = daily_tss.get(d, 0.0) + (w["tss"] or 0.0)

    if not daily_tss:
        return

    # 3. Recalculate PMC with Seeding Strategy
    all_dates = sorted(daily_tss.keys())
    start_date, end_date = all_dates[0], all_dates[-1]
    
    # Calculate the average TSS of the first 42 days to seed the history.
    # This matches the user's new algorithm intent to solve the "cold start" problem.
    initial_window = [daily_tss.get(d, 0.0) for d in all_dates[:42]]
    avg_tss = sum(initial_window) / len(initial_window) if initial_window else 0.0
    
    # spans match algorithms.py (alpha = 2 / (span + 1))
    ctl_alpha = 2 / (42 + 1)
    atl_alpha = 2 / (7 + 1)
    
    ctl, atl = avg_tss, avg_tss
    
    records = []
    current = start_date
    while current <= end_date:
        tss = daily_tss.get(current, 0.0)
        ctl = ctl * (1 - ctl_alpha) + tss * ctl_alpha
        atl = atl * (1 - atl_alpha) + tss * atl_alpha
        
        records.append({
            "athlete_id": athlete_id,
            "date": current.isoformat(),
            "daily_tss": round(tss, 2),
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(ctl - atl, 2)
        })
        current += timedelta(days=1)

    # 4. Save to tss_history table
    if records:
        # PostgREST upsert handles batches well
        db.table("tss_history").upsert(records, on_conflict="athlete_id,date").execute()

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
        "duration_seconds": duration_seconds,
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
    }, on_conflict="source,external_id").execute()

    # 5. Trigger Full Load Recalculation (PMC)
    recalculate_tss_history(athlete_id, db)


def process_and_save_biometrics(payload: DailyBiometrics, athlete_id: str, db):
    # 1. Handle Sleep Periods (if sleep data is present)
    has_sleep_session = payload.sleep_bedtime is not None and payload.sleep_wakeup is not None
    
    if has_sleep_session:
        # Save this specific session to sleep_periods table
        # We use a helper to extract the session-specific fields
        session_data = {
            "athlete_id": athlete_id,
            "date": payload.date.isoformat(),
            "started_at": payload.sleep_bedtime.isoformat() if payload.sleep_bedtime else None,
            "ended_at": payload.sleep_wakeup.isoformat() if payload.sleep_wakeup else None,
            "duration_min": payload.sleep_duration_min or 0,
            "score": payload.sleep_score,
            "deep_pct": payload.sleep_deep_pct,
            "rem_pct": payload.sleep_rem_pct,
            "light_pct": payload.sleep_light_pct,
            "awake_pct": payload.sleep_awake_pct,
            "is_nap": payload.is_nap or False,
            "source": payload.source,
            "external_id": getattr(payload, "external_id", None) or f"{payload.source}_{payload.sleep_bedtime.timestamp() if payload.sleep_bedtime else payload.date.isoformat()}"
        }
        db.table("sleep_periods").upsert(session_data, on_conflict="source,external_id").execute()

    # 2. Fetch All Sleep Periods for the biological day to aggregate
    all_periods_res = db.table("sleep_periods").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).execute()
    all_periods = []
    if all_periods_res and all_periods_res.data:
        all_periods = all_periods_res.data
    
    total_sleep_min = 0
    weighted_deep = 0.0
    weighted_rem = 0.0
    weighted_light = 0.0
    weighted_awake = 0.0
    
    main_sleep = None
    max_duration = -1
    
    for p in all_periods:
        dur = p.get("duration_min") or 0
        total_sleep_min += dur
        weighted_deep += (p.get("deep_pct") or 0) * dur
        weighted_rem += (p.get("rem_pct") or 0) * dur
        weighted_light += (p.get("light_pct") or 0) * dur
        weighted_awake += (p.get("awake_pct") or 0) * dur
        
        if dur > max_duration:
            max_duration = dur
            main_sleep = p

    # Final aggregated architecture (weighted by duration)
    agg_deep = round(weighted_deep / total_sleep_min, 1) if total_sleep_min > 0 else None
    agg_rem = round(weighted_rem / total_sleep_min, 1) if total_sleep_min > 0 else None
    agg_light = round(weighted_light / total_sleep_min, 1) if total_sleep_min > 0 else None
    agg_awake = round(weighted_awake / total_sleep_min, 1) if total_sleep_min > 0 else None

    # 3. Fetch Previous Day's Biometrics (for sleep debt/strain)
    prev_date = payload.date - timedelta(days=1)
    prev_res = db.table("biometrics").select("sleep_debt_min, astrape_strain_score").eq("athlete_id", athlete_id).eq("date", prev_date.isoformat()).maybe_single().execute()
    
    prev_debt = 0.0
    prev_strain = 0.0
    if prev_res and prev_res.data:
        prev_debt = prev_res.data.get("sleep_debt_min") or 0.0
        # Priority: Astrape Custom Strain Score
        prev_strain = prev_res.data.get("astrape_strain_score") or 0.0
        
    # 4. Calculate Dynamic Baselines & Targets
    start_date_42d = (payload.date - timedelta(days=42)).isoformat()
    history_res = db.table("biometrics").select("resting_hr, hrv_rmssd").eq("athlete_id", athlete_id).gte("date", start_date_42d).order("date").execute()
    athlete_res = db.table("athletes").select("*").eq("id", athlete_id).single().execute()
    
    baseline_rhr = 50.0
    baseline_hrv = 65.0
    athlete_data = athlete_res.data if athlete_res else {}
    
    if history_res and history_res.data:
        rhrs = [row["resting_hr"] for row in history_res.data if row["resting_hr"] is not None]
        hrvs = [float(row["hrv_rmssd"]) for row in history_res.data if row["hrv_rmssd"] is not None]
        
        # Include today's data in the baseline calculation
        if payload.resting_hr is not None: rhrs.append(payload.resting_hr)
        if payload.hrv_rmssd is not None: hrvs.append(payload.hrv_rmssd)
        
        if rhrs: baseline_rhr = calculate_rhr_baseline(rhrs)
        if hrvs: baseline_hrv = calculate_hrv_baseline(hrvs)

    # 4.5 Update Athlete Profile with latest physiological state
    # Fetch current CTL for TSS target calculation
    ctl_res = db.table("tss_history").select("ctl").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).maybe_single().execute()
    current_ctl = ctl_res.data["ctl"] if (ctl_res and ctl_res.data) else 0.0
    
    profile_updates = {
        "rhr_baseline": int(round(baseline_rhr)),
        "hrv_baseline": round(baseline_hrv, 1),
        "resting_hr": int(round(baseline_rhr)), # Sync current resting_hr with baseline
        "weekly_tss_target": calculate_weekly_tss_target(current_ctl)
    }
    
    # Estimate Threshold HR if missing (using HRR method: 83% intensity)
    if athlete_data.get("max_hr") and not athlete_data.get("threshold_hr"):
        profile_updates["threshold_hr"] = calculate_threshold_hr_est(
            max_hr=athlete_data["max_hr"],
            resting_hr=int(round(baseline_rhr))
        )
    
    db.table("athletes").update(profile_updates).eq("id", athlete_id).execute()
    
    # 5. Fetch ATL Data for Readiness Modeling
    start_date_30d = (payload.date - timedelta(days=30)).isoformat()
    atl_res = db.table("tss_history").select("atl").eq("athlete_id", athlete_id).gte("date", start_date_30d).order("date").execute()
    
    prior_day_atl = 0.0
    prior_day_atl_max_30d = 1.0 
    
    if atl_res and atl_res.data:
        atls = [row["atl"] for row in atl_res.data if row["atl"] is not None]
        if atls:
            prior_day_atl_max_30d = max(atls) or 1.0
            prior_day_atl = atls[-1]
            
    # 6. Process Sleep Architecture (Aggregated)
    astrape_need = calculate_astrape_sleep_need(480, prev_strain, prev_debt)
    
    astrape_sleep = calculate_astrape_sleep_score(
        duration_min=total_sleep_min,
        sleep_need_min=astrape_need,
        rem_pct=agg_rem,
        deep_pct=agg_deep
    )

    next_night_debt = min(120, max(0, astrape_need - total_sleep_min))

    # 7. Merge with existing Biometrics row (HRV/RHR/Strain)
    existing_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).maybe_single().execute()
    existing = {}
    if existing_res and existing_res.data:
        existing = existing_res.data

    # 7.5 Calculate Daily Astrape Strain from Workouts
    # Fetch all workouts for this day to aggregate raw strain
    day_workouts_res = db.table("workouts").select("hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct, duration_seconds").eq("athlete_id", athlete_id).filter("started_at", "gte", payload.date.isoformat()).filter("started_at", "lt", (payload.date + timedelta(days=1)).isoformat()).execute()
    
    total_zone_minutes = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    if day_workouts_res and day_workouts_res.data:
        for w in day_workouts_res.data:
            dur_sec = w.get("duration_seconds") or 0
            for z in range(1, 6):
                pct = w.get(f"hr_zone_{z}_pct") or 0
                total_zone_minutes[z] += (pct / 100.0) * (dur_sec / 60.0)
    
    astrape_day_raw_strain = calculate_raw_strain_score(total_zone_minutes)
    astrape_day_strain = calculate_astrape_strain_score(astrape_day_raw_strain)

    final_hrv = payload.hrv_rmssd if payload.hrv_rmssd is not None else existing.get("hrv_rmssd")
    final_rhr = payload.resting_hr if payload.resting_hr is not None else existing.get("resting_hr")
    # We still keep WHOOP strain in day_strain for comparison, but Astrape will use its own
    final_strain = payload.day_strain if payload.day_strain is not None else existing.get("day_strain")
    final_temp = payload.skin_temp_deviation if payload.skin_temp_deviation is not None else existing.get("skin_temp_deviation")
    final_spo2 = payload.spo2_pct if payload.spo2_pct is not None else existing.get("spo2_pct")
    final_recovery = payload.recovery_score if payload.recovery_score is not None else existing.get("recovery_score")
    final_source = payload.source if payload.hrv_rmssd is not None else existing.get("hrv_source", payload.source)

    # 8. Process Recovery (Autonomic Repair)
    astrape_recovery = calculate_astrape_recovery_score(
        hrv_rmssd=final_hrv or 0.0,
        hrv_baseline_30d=baseline_hrv,
        resting_hr=final_rhr or 0,
        resting_hr_baseline_30d=baseline_rhr,
        sleep_score=astrape_sleep
    )
    
    # 9. Process Readiness (Capacity to Train)
    astrape_readiness = calculate_astrape_readiness_score(
        recovery_score=astrape_recovery,
        prior_day_atl=prior_day_atl,
        prior_day_atl_max_30d=prior_day_atl_max_30d,
        skin_temp_deviation=final_temp or 0.0,
        spo2_pct=final_spo2 or 100.0
    )
    
    # 10. Save aggregated record to biometrics
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "hrv_rmssd": final_hrv,
        "resting_hr": final_rhr,
        "sleep_duration_min": total_sleep_min,
        "sleep_score": main_sleep.get("score") if main_sleep else payload.sleep_score,
        "recovery_score": final_recovery,
        "sleep_need_min": astrape_need,
        "sleep_debt_min": next_night_debt,
        "astrape_sleep_score": astrape_sleep,
        "astrape_recovery_score": astrape_recovery,
        "astrape_readiness_score": astrape_readiness,
        "astrape_strain_score": astrape_day_strain,
        "hrv_source": final_source,
        "sleep_deep_pct": agg_deep,
        "sleep_rem_pct": agg_rem,
        "sleep_light_pct": agg_light,
        "sleep_awake_pct": agg_awake,
        "sleep_bedtime": main_sleep.get("started_at") if main_sleep else None,
        "sleep_wakeup": main_sleep.get("ended_at") if main_sleep else None,
        "skin_temp_deviation": final_temp,
        "spo2_pct": final_spo2,
        "day_strain": final_strain
    }, on_conflict="athlete_id,date").execute()