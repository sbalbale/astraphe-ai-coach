from datetime import date, timedelta, datetime
import numpy as np
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics

from app.services.algorithms import (
    compute_tss_power, 
    compute_hrss_from_zones,
    compute_trss_pace,
    compute_ctl,
    compute_atl,
    compute_sleep_score,
    compute_sleep_need,
    DEFAULT_BASELINE_SLEEP_MIN,
    MAX_SLEEP_DEBT_MIN,
    SLEEP_DEBT_DECAY_RATE,
    normalize_rowing_watts,
    compute_strain_score,
    compute_recovery_score,
    compute_readiness_score,
    calculate_rhr_baseline,
    calculate_hrv_baseline,
    calculate_spo2_baseline,
    calculate_temp_baseline,
    calculate_weekly_tss_target,
    calculate_threshold_hr_est
)

def _parse_pace_to_sec_per_km(pace: object) -> float:
    """
    Accepts pace like '5:00', '05:00', '5:00/km', returns seconds per km.
    Returns 0.0 for invalid inputs.
    """
    if pace is None:
        return 0.0
    if isinstance(pace, (int, float)):
        return float(pace) if float(pace) > 0 else 0.0

    s = str(pace).strip().lower()
    if not s:
        return 0.0

    # remove common suffixes
    for suffix in ("/km", "per km", "km", "min/km"):
        s = s.replace(suffix, "")
    s = s.strip()

    # Support "m:ss" or "mm:ss"
    if ":" in s:
        parts = [p for p in s.split(":") if p != ""]
        if len(parts) == 2:
            try:
                mins = int(parts[0])
                secs = int(parts[1])
                total = mins * 60 + secs
                return float(total) if total > 0 else 0.0
            except Exception:
                return 0.0

    # Fallback: treat as numeric seconds
    try:
        v = float(s)
        return v if v > 0 else 0.0
    except Exception:
        return 0.0

def recalculate_tss_history(athlete_id: str, db):
    """
    Fetches all workouts for an athlete, aggregates TSS by date,
    and recalculates the entire PMC (CTL/ATL/TSB) history.
    """
    # 1. Fetch all workouts with TSS
    res = db.table("workouts").select("started_at, tss").eq("athlete_id", athlete_id).order("started_at").execute()
    if not res or not res.data:
        return

    # 1.5 Fetch athlete timezone for correct date mapping
    athlete_res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).single().execute()
    offset = (athlete_res.data.get("timezone_offset_min") or 0) if athlete_res.data else 0

    # 2. Aggregate TSS by date
    daily_tss = {}
    for w in res.data:
        # Parse ISO string and adjust for athlete's local offset
        utc_start = datetime.fromisoformat(w["started_at"].replace("Z", "+00:00"))
        local_start = utc_start + timedelta(minutes=offset)
        d = local_start.date()
        daily_tss[d] = daily_tss.get(d, 0.0) + (w["tss"] or 0.0)

    if not daily_tss:
        return

    # 3. Recalculate PMC with New proprietary Seeding Strategy
    all_dates = sorted(daily_tss.keys())
    if not all_dates:
        return

    start_date, end_date = all_dates[0], all_dates[-1]
    
    # Extract TSS series as numpy array for compute_ctl/atl
    # Fill in missing days with 0.0
    tss_list = []
    current = start_date
    while current <= end_date:
        tss_list.append(daily_tss.get(current, 0.0))
        current += timedelta(days=1)
    
    tss_series = np.array(tss_list)
    ctl_series = compute_ctl(tss_series)
    atl_series = compute_atl(tss_series)
    
    records = []
    current = start_date
    for i in range(len(tss_series)):
        ctl = ctl_series[i]
        atl = atl_series[i]
        records.append({
            "athlete_id": athlete_id,
            "date": current.isoformat(),
            "daily_tss": round(float(tss_series[i]), 2),
            "ctl": round(float(ctl), 2),
            "atl": round(float(atl), 2),
            "tsb": round(float(ctl - atl), 2)
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

    # Map sport to internal enum conventions
    mapped_sport = sport if sport in ('run', 'bike', 'swim', 'strength', 'rowing') else 'other'
    if sport == 'cycling': mapped_sport = 'bike'

    # Load athlete anchors needed for HRSS / pace-based models
    athlete_res = db.table("athletes").select("max_hr,resting_hr,threshold_hr,threshold_pace,gender").eq("id", athlete_id).single().execute()
    athlete = athlete_res.data if (athlete_res and athlete_res.data) else {}

    anchor_max_hr = athlete.get("max_hr") or payload.max_hr
    anchor_resting_hr = athlete.get("resting_hr")
    anchor_threshold_hr = athlete.get("threshold_hr")
    anchor_gender = athlete.get("gender") or "male"
    threshold_pace_sec_km = _parse_pace_to_sec_per_km(athlete.get("threshold_pace"))

    # 2. Calculate Training Stress Score (TSS)
    if sport == "cycling" and payload.normalized_power:
        tss = compute_tss_power(payload.duration_seconds, payload.normalized_power, payload.ftp_at_time)
    elif mapped_sport == "run" and payload.duration_seconds and payload.avg_pace_sec_km and threshold_pace_sec_km > 0:
        # Use pace-based load when threshold pace is available (speed-based tracking)
        tss = compute_trss_pace(
            duration_sec=payload.duration_seconds,
            avg_pace_sec_km=float(payload.avg_pace_sec_km),
            threshold_pace_sec_km=float(threshold_pace_sec_km),
        )
    elif has_hr_zones and payload.duration_seconds:
        # Use Banister TRIMP HRSS estimated from time-in-zone (historical aggregate)
        safe_hr_zones = {k: float(v or 0.0) for k, v in hr_zones.items()}
        if hr_zone_0_pct is not None:
            safe_hr_zones[0] = float(hr_zone_0_pct or 0.0)

        zone_minutes = {k: (v / 100.0) * (payload.duration_seconds / 60.0) for k, v in safe_hr_zones.items()}
        tss = compute_hrss_from_zones(
            zone_minutes=zone_minutes,
            max_hr=int(anchor_max_hr or 0),
            resting_hr=int(anchor_resting_hr or 0),
            threshold_hr=int(anchor_threshold_hr or 0),
            sport=mapped_sport,
            gender=str(anchor_gender),
        )
    elif sport == "rowing" and hasattr(payload, 'avg_power') and payload.avg_power:
        # Fallback for rowing
        norm_watts = normalize_rowing_watts(payload.avg_power)
        tss = compute_tss_power(payload.duration_seconds, int(norm_watts), payload.ftp_at_time)
    elif getattr(payload, "tss", None):
        tss = getattr(payload, "tss")
    
    # Duration / end time alignment
    duration_seconds = payload.duration_seconds
    ended_at = payload.ended_at
    if ended_at is None and payload.start_time and duration_seconds:
        ended_at = payload.start_time + timedelta(seconds=duration_seconds)
    if duration_seconds is None and payload.start_time and ended_at:
        duration_seconds = int(max(0, (ended_at - payload.start_time).total_seconds()))

    # 3. Calculate Physiological Cardiovascular Strain (0-100 scale)
    strain_score = 0
    if has_hr_zones and duration_seconds:
        # Convert the None values to 0.0 for safety
        safe_hr_zones = {k: (v or 0.0) for k, v in hr_zones.items()}
        # Get duration in minutes for the specific zones
        zone_minutes = {k: (v / 100.0) * (duration_seconds / 60.0) for k, v in safe_hr_zones.items()}
        strain_score = compute_strain_score(zone_minutes)

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
        "strain_score": strain_score,
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
        
        # Calculate durations from timestamps to ensure consistency
        in_bed_min = 0
        if payload.sleep_bedtime and payload.sleep_wakeup:
            delta = payload.sleep_wakeup - payload.sleep_bedtime
            in_bed_min = int(round(delta.total_seconds() / 60.0))
        
        # Derive actual sleep duration: Time in Bed * (1 - Awake%)
        # This ensures mathematical integrity: Asleep + Awake = In Bed
        awake_pct = payload.sleep_awake_pct or 0.0
        actual_sleep_min = int(round(in_bed_min * (1.0 - (awake_pct / 100.0))))
        
        # If payload already has a duration, we might prefer it IF it's consistent, 
        # but the user specifically asked for the backend to handle the math.
        session_duration = actual_sleep_min
        
        session_data = {
            "athlete_id": athlete_id,
            "date": payload.date.isoformat(),
            "started_at": payload.sleep_bedtime.isoformat() if payload.sleep_bedtime else None,
            "ended_at": payload.sleep_wakeup.isoformat() if payload.sleep_wakeup else None,
            "duration_min": session_duration,
            "in_bed_min": in_bed_min,
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
    total_in_bed_min = 0
    total_awake_min = 0
    weighted_deep = 0.0
    weighted_rem = 0.0
    weighted_light = 0.0
    weighted_awake = 0.0
    
    main_sleep = None
    max_in_bed = -1
    
    for p in all_periods:
        in_bed = p.get("in_bed_min") or p.get("duration_min") or 0
        total_in_bed_min += in_bed
        
        # Calculate awake minutes for this period to ensure consistency
        awake_pct = p.get("awake_pct") or 0.0
        awake_min = (awake_pct / 100.0) * in_bed
        total_awake_min += awake_min
        
        # Weight percentages by in_bed_min
        weighted_deep += (p.get("deep_pct") or 0) * in_bed
        weighted_rem += (p.get("rem_pct") or 0) * in_bed
        weighted_light += (p.get("light_pct") or 0) * in_bed
        weighted_awake += awake_pct * in_bed
        
        if in_bed > max_in_bed:
            max_in_bed = in_bed
            main_sleep = p

    # Final aggregated architecture (weighted by in-bed duration)
    agg_deep = round(weighted_deep / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_rem = round(weighted_rem / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_light = round(weighted_light / total_in_bed_min, 1) if total_in_bed_min > 0 else None
    agg_awake = round(weighted_awake / total_in_bed_min, 1) if total_in_bed_min > 0 else None

    # Time Asleep MUST equal Time in Bed minus Awake Time
    total_sleep_min = int(round(total_in_bed_min - total_awake_min))

    # 3. Fetch Previous Day's Biometrics (for sleep debt/strain)
    prev_date = payload.date - timedelta(days=1)
    prev_res = db.table("biometrics").select("sleep_debt_min, strain_score").eq("athlete_id", athlete_id).eq("date", prev_date.isoformat()).maybe_single().execute()
    
    prev_debt = 0.0
    prev_strain = 0
    if prev_res and prev_res.data:
        prev_debt = prev_res.data.get("sleep_debt_min") or 0.0
        # Priority: Astrape Custom Strain Score
        prev_strain = prev_res.data.get("strain_score") or 0
        
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
    # New proprietary sleep need calculation logic should be integrated if different, 
    # but for now we follow the user's provided compute_sleep_score.
    # The sleep need still uses a baseline (e.g. 480) + strain/debt impact.
    carried_debt = float(prev_debt or 0.0) * SLEEP_DEBT_DECAY_RATE
    sleep_need = compute_sleep_need(
        baseline_min=DEFAULT_BASELINE_SLEEP_MIN,
        strain_score=int(prev_strain or 0),
        current_debt_min=carried_debt,
    )
    
    sleep_score = compute_sleep_score(
        actual_sleep_min=total_sleep_min,
        sleep_need_min=sleep_need,
        rem_pct=agg_rem,
        deep_pct=agg_deep
    )

    next_night_debt = float(np.clip(float(sleep_need) - float(total_sleep_min), 0.0, MAX_SLEEP_DEBT_MIN))

    # 7. Merge with existing Biometrics row (HRV/RHR/Strain)
    existing_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).maybe_single().execute()
    existing = {}
    if existing_res and existing_res.data:
        existing = existing_res.data

    # 7.5 Calculate Daily Astrape Strain from Workouts
    # Fetch all workouts for this day to aggregate raw strain
    day_workouts_res = db.table("workouts").select("hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct, duration_seconds").eq("athlete_id", athlete_id).filter("started_at", "gte", payload.date.isoformat()).filter("started_at", "lt", (payload.date + timedelta(days=1)).isoformat()).execute()
    
    day_zone_minutes = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    if day_workouts_res and day_workouts_res.data:
        for w in day_workouts_res.data:
            dur_sec = w.get("duration_seconds") or 0
            for z in range(1, 6):
                pct = w.get(f"hr_zone_{z}_pct") or 0
                day_zone_minutes[z] += (pct / 100.0) * (dur_sec / 60.0)
    
    astrape_strain_score = compute_strain_score(day_zone_minutes)

    final_hrv = payload.hrv_rmssd if payload.hrv_rmssd is not None else existing.get("hrv_rmssd")
    final_rhr = payload.resting_hr if payload.resting_hr is not None else existing.get("resting_hr")
    final_temp = payload.skin_temp_deviation if payload.skin_temp_deviation is not None else existing.get("skin_temp_deviation")
    final_spo2 = payload.spo2_pct if payload.spo2_pct is not None else existing.get("spo2_pct")
    final_source = payload.source if payload.hrv_rmssd is not None else existing.get("hrv_source", payload.source)

    # 8. Process Recovery (Autonomic Repair)
    recovery_score = compute_recovery_score(
        hrv_today=final_hrv or 0.0,
        hrv_baseline_30d=baseline_hrv,
        resting_hr=final_rhr or 0,
        resting_hr_baseline_30d=baseline_rhr,
        sleep_score=sleep_score,
        prior_day_atl=prior_day_atl,
        prior_day_atl_max_30d=prior_day_atl_max_30d,
        skin_temp_deviation=final_temp or 0.0,
        spo2_pct=final_spo2 or 100.0
    )
    
    # 9. Process Readiness (Capacity to Train)
    # TSB based readiness
    readiness_score = compute_readiness_score(current_ctl - prior_day_atl)
    
    # 10. Save aggregated record to biometrics
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "hrv_rmssd": final_hrv,
        "resting_hr": final_rhr,
        "sleep_duration_min": total_sleep_min,
        "sleep_in_bed_min": total_in_bed_min,
        "sleep_score": sleep_score, # Astrape Score
        "recovery_score": recovery_score, # Astrape Score
        "sleep_need_min": int(round(sleep_need)),
        "sleep_debt_min": int(round(next_night_debt)),
        "readiness_score": readiness_score,
        "strain_score": astrape_strain_score,
        "hrv_source": final_source,
        "sleep_deep_pct": agg_deep,
        "sleep_rem_pct": agg_rem,
        "sleep_light_pct": agg_light,
        "sleep_awake_pct": agg_awake,
        "sleep_bedtime": main_sleep.get("started_at") if main_sleep else None,
        "sleep_wakeup": main_sleep.get("ended_at") if main_sleep else None,
        "skin_temp_deviation": final_temp,
        "spo2_pct": final_spo2
    }, on_conflict="athlete_id,date").execute()