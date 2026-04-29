import os
import sys
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import date, timedelta, datetime
from typing import Dict, List, Any

# Add backend to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(REPO_ROOT / "backend"))

from app.services.algorithms import (
    compute_ctl,
    compute_atl,
    compute_strain_score,
    compute_readiness_score,
    compute_sleep_score,
    compute_sleep_need,
    compute_recovery_score,
    calculate_rhr_baseline,
    calculate_hrv_baseline,
    DEFAULT_BASELINE_SLEEP_MIN,
    MAX_SLEEP_DEBT_MIN,
    SLEEP_DEBT_DECAY_RATE
)

def main():
    load_dotenv(REPO_ROOT / "backend" / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("Missing Supabase credentials")
        return

    db: Client = create_client(url, key)
    
    # 1. Fetch all athletes
    athletes = db.table("athletes").select("id, display_name").execute()
    
    for athlete in athletes.data:
        athlete_id = athlete["id"]
        print(f"\n>>> Processing Athlete: {athlete['display_name']} ({athlete_id})")
        
        # --- 1. PMC RECALCULATION ---
        print("Recalculating PMC (CTL/ATL/TSB)...")
        workouts_res = db.table("workouts").select("started_at, tss, duration_seconds, hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct").eq("athlete_id", athlete_id).order("started_at").execute()
        
        daily_tss = {}
        daily_zones = {} # For daily strain
        
        for w in workouts_res.data:
            d_str = w["started_at"][:10]
            d = date.fromisoformat(d_str)
            daily_tss[d] = daily_tss.get(d, 0.0) + (w["tss"] or 0.0)
            
            # Aggregate zone minutes for daily strain
            if d not in daily_zones:
                daily_zones[d] = {z: 0.0 for z in range(1, 6)}
            
            dur_min = (w.get("duration_seconds") or 0) / 60.0
            for z in range(1, 6):
                pct = w.get(f"hr_zone_{z}_pct") or 0
                daily_zones[d][z] += (pct / 100.0) * dur_min
        
        if not daily_tss:
            print("No workouts found. Skipping PMC.")
            all_dates = []
        else:
            sorted_workout_dates = sorted(daily_tss.keys())
            start_date = sorted_workout_dates[0]
            end_date = date.today()
            
            tss_list = []
            curr = start_date
            while curr <= end_date:
                tss_list.append(daily_tss.get(curr, 0.0))
                curr += timedelta(days=1)
            
            tss_series = np.array(tss_list)
            ctl_series = compute_ctl(tss_series)
            atl_series = compute_atl(tss_series)
            
            history_updates = []
            curr = start_date
            for i in range(len(tss_series)):
                ctl = ctl_series[i]
                atl = atl_series[i]
                history_updates.append({
                    "athlete_id": athlete_id,
                    "date": curr.isoformat(),
                    "daily_tss": round(float(tss_series[i]), 2),
                    "ctl": round(float(ctl), 2),
                    "atl": round(float(atl), 2),
                    "tsb": round(float(ctl - atl), 2)
                })
                curr += timedelta(days=1)
            
            if history_updates:
                print(f"Upserting {len(history_updates)} PMC records...")
                for i in range(0, len(history_updates), 100):
                    db.table("tss_history").upsert(history_updates[i:i+100], on_conflict="athlete_id,date").execute()

        # --- 2. BIOMETRICS RECALCULATION ---
        print("Recalculating Proprietary Biometric Scores...")
        bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date").execute()
        if not bio_res.data:
            print("No biometrics found.")
            continue
            
        # Build atl map for recovery calc
        atl_map = {date.fromisoformat(h["date"]): h["atl"] for h in (history_updates if 'history_updates' in locals() else [])}
        
        # For rolling baselines, we'll keep buffers
        hrv_history = []
        rhr_history = []
        atl_history_30d = []
        
        # Track sleep debt across days
        current_sleep_debt = 0.0
        
        bio_updates = []
        
        for idx, row in enumerate(bio_res.data):
            curr_date = date.fromisoformat(row["date"])
            
            # Update rolling buffers
            hrv = row.get("hrv_rmssd")
            if hrv: hrv_history.append(hrv)
            rhr = row.get("resting_hr")
            if rhr: rhr_history.append(rhr)
            
            # Prior day ATL
            prior_date = curr_date - timedelta(days=1)
            prior_atl = atl_map.get(prior_date, 0.0)
            atl_history_30d.append(prior_atl)
            if len(atl_history_30d) > 30: atl_history_30d.pop(0)
            
            # Baselines (using 30d for score, but 42d for long-term if wanted. Algorithms use 30d/42d mixed)
            # We'll use 42d history for the baseline functions to be safe.
            hrv_baseline = calculate_hrv_baseline(hrv_history)
            rhr_baseline = calculate_rhr_baseline(rhr_history)
            max_atl_30d = max(atl_history_30d) if atl_history_30d else 1.0
            
            # 1. Strain Score
            zones = daily_zones.get(curr_date, {z: 0.0 for z in range(1, 6)})
            strain_score = compute_strain_score(zones)
            
            # 2. Sleep Need & Score
            # Base need is 480m (8h). 
            # Plus impact from previous day's strain and debt.
            # We look at the strain_score calculated in the previous step for the prior day
            prior_bio = bio_updates[-1] if len(bio_updates) > 0 else {}
            prev_strain = prior_bio.get("strain_score", 0)

            carried_debt = float(current_sleep_debt) * SLEEP_DEBT_DECAY_RATE
            sleep_need = compute_sleep_need(
                baseline_min=DEFAULT_BASELINE_SLEEP_MIN,
                strain_score=int(prev_strain or 0),
                current_debt_min=carried_debt,
            )
            
            duration = row.get("sleep_duration_min") or 0
            sleep_score = compute_sleep_score(
                actual_sleep_min=duration,
                sleep_need_min=sleep_need,
                rem_pct=row.get("sleep_rem_pct"),
                deep_pct=row.get("sleep_deep_pct")
            )
            
            # Update debt for the next day (decay + strict physiological cap)
            current_sleep_debt = float(np.clip(float(sleep_need) - float(duration), 0.0, MAX_SLEEP_DEBT_MIN))
            
            # 3. Recovery Score
            recovery_score = compute_recovery_score(
                hrv_today=hrv or 0.0,
                hrv_baseline_30d=hrv_baseline,
                resting_hr=rhr or 0,
                resting_hr_baseline_30d=rhr_baseline,
                sleep_score=sleep_score,
                prior_day_atl=prior_atl,
                prior_day_atl_max_30d=max_atl_30d,
                skin_temp_deviation=row.get("skin_temp_deviation") or 0.0,
                spo2_pct=row.get("spo2_pct") or 100.0
            )
            
            # 4. Readiness Score
            current_ctl = atl_map.get(curr_date, 0.0)
            readiness_score = compute_readiness_score(current_ctl - prior_atl)
            
            bio_updates.append({
                "athlete_id": athlete_id,
                "date": row["date"],
                "strain_score": strain_score,
                "sleep_score": sleep_score,
                "sleep_need_min": int(round(sleep_need)),
                "sleep_debt_min": int(round(current_sleep_debt)),
                "recovery_score": recovery_score,
                "readiness_score": readiness_score
            })
            
            # Keep buffers capped at 42 for baselines
            if len(hrv_history) > 42: hrv_history.pop(0)
            if len(rhr_history) > 42: rhr_history.pop(0)

        if bio_updates:
            print(f"Upserting {len(bio_updates)} biometric scores...")
            for i in range(0, len(bio_updates), 100):
                db.table("biometrics").upsert(bio_updates[i:i+100], on_conflict="athlete_id,date").execute()
                
    print("\n[OK] All metrics recalculated.")

if __name__ == "__main__":
    main()
