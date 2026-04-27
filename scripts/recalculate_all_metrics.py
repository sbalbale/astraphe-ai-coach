import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import date, timedelta
import pandas as pd

# Add backend to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(REPO_ROOT / "backend"))

from app.services.algorithms import calculate_recovery_score, calculate_training_load

def main():
    load_dotenv(REPO_ROOT / "backend" / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("Missing Supabase credentials")
        return

    db: Client = create_client(url, key)
    
    # 1. Fetch all athletes
    athletes = db.table("athletes").select("id, display_name, hrv_baseline, rhr_baseline").execute()
    
    for athlete in athletes.data:
        athlete_id = athlete["id"]
        print(f"\nProcessing Athlete: {athlete['display_name']} ({athlete_id})")
        
        baseline_hrv = athlete.get("hrv_baseline") or 65.0
        baseline_rhr = athlete.get("rhr_baseline") or 50

        # 2. Refresh Biometrics Recovery Scores
        print("Refreshing biometrics recovery scores...")
        bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).execute()
        
        updates = []
        for row in bio_res.data:
            new_score = calculate_recovery_score(
                hrv=row.get("hrv_rmssd") or 0.0,
                baseline_hrv=baseline_hrv,
                sleep_score=row.get("sleep_score") or 0,
                resting_hr=row.get("resting_hr") or 0,
                baseline_rhr=baseline_rhr
            )
            updates.append({
                "athlete_id": athlete_id,
                "date": row["date"],
                "recovery_score": new_score
            })
        
        if updates:
            # Batch upsert in chunks of 100
            for i in range(0, len(updates), 100):
                db.table("biometrics").upsert(updates[i:i+100]).execute()
        
        # 3. Refresh TSS History (PMC)
        print("Recalculating TSS history (PMC)...")
        workouts = db.table("workouts").select("started_at, tss").eq("athlete_id", athlete_id).execute()
        
        daily_tss = {}
        for w in workouts.data:
            d = w["started_at"][:10]
            daily_tss[d] = daily_tss.get(d, 0.0) + (w["tss"] or 0.0)
            
        if not daily_tss:
            print("No workouts found for this athlete.")
            continue
            
        sorted_dates = sorted(daily_tss.keys())
        all_tss_values = [daily_tss[d] for d in sorted_dates]
        
        # We need to compute PMC longitudinally
        # The calculate_training_load function in algorithms.py only gives the LATEST value
        # We need a variant or just loop through and build it
        
        # Standard constants
        ctl_decay = 1 - (1/42)
        atl_decay = 1 - (1/7)
        
        history_updates = []
        current_ctl = 0.0
        current_atl = 0.0
        
        # Fill date gaps to ensure decay works correctly
        start_date = date.fromisoformat(sorted_dates[0])
        end_date = date.fromisoformat(sorted_dates[-1])
        curr = start_date
        while curr <= end_date:
            curr_str = curr.isoformat()
            tss = daily_tss.get(curr_str, 0.0)
            
            # Simple EMA implementation matching pandas span=42/7 adjust=False
            # current = last * (1 - alpha) + new * alpha
            # for span=N, alpha = 2/(N+1)
            alpha_ctl = 2 / (42 + 1)
            alpha_atl = 2 / (7 + 1)
            
            if curr == start_date:
                current_ctl = tss
                current_atl = tss
            else:
                current_ctl = current_ctl * (1 - alpha_ctl) + tss * alpha_ctl
                current_atl = current_atl * (1 - alpha_atl) + tss * alpha_atl
            
            history_updates.append({
                "athlete_id": athlete_id,
                "date": curr_str,
                "daily_tss": round(tss, 2),
                "ctl": round(current_ctl, 1),
                "atl": round(current_atl, 1),
                "tsb": round(current_ctl - current_atl, 1)
            })
            curr += timedelta(days=1)
            
        if history_updates:
            for i in range(0, len(history_updates), 100):
                db.table("tss_history").upsert(history_updates[i:i+100]).execute()
        
        print(f"Done. Processed {len(updates)} biometrics and {len(history_updates)} days of TSS history.")

if __name__ == "__main__":
    main()
