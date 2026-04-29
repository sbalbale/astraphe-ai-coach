import sys
import os
from datetime import datetime, timedelta

# Add the parent directory to sys.path so we can import from 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.processing import process_and_save_biometrics
from app.models.biometrics import DailyBiometrics

def cleanup_sleep_data():
    db = get_admin_db()
    print("--- Starting Sleep Data Cleanup ---")

    # 1. Identify corrupted sleep periods
    # We fetch periods where duration_min > 24 hours (1440 mins) 
    # OR where duration_min exceeds wall-clock time between started_at and ended_at
    periods_res = db.table("sleep_periods").select("*").execute()
    
    corrupted_count = 0
    fixed_dates = set() # (athlete_id, date)

    for p in periods_res.data:
        started_at = datetime.fromisoformat(p["started_at"].replace("Z", "+00:00"))
        ended_at = datetime.fromisoformat(p["ended_at"].replace("Z", "+00:00"))
        wall_clock_min = (ended_at - started_at).total_seconds() / 60
        
        reported_min = p["duration_min"] or 0
        
        # If reported sleep is > wall clock time, it's corrupted by the feedback loop
        if reported_min > (wall_clock_min + 5): # 5 min buffer for rounding
            print(f"Found corrupted period: {p['id']} on {p['date']} | Reported: {reported_min}m | Wall Clock: {int(wall_clock_min)}m")
            
            # Reset to wall clock time * 0.9 (rough estimate of asleep time) 
            # or better, just fix it during reprocessing.
            # For now, let's just delete the corrupted record so it can be re-synced 
            # or set it to a sane value.
            new_dur = int(wall_clock_min * 0.92) # Typical WHOOP efficiency
            db.table("sleep_periods").update({"duration_min": new_dur}).eq("id", p["id"]).execute()
            
            corrupted_count += 1
            fixed_dates.add((p["athlete_id"], p["date"]))

    print(f"Fixed {corrupted_count} corrupted sleep periods.")

    # 2. Trigger re-aggregation for affected days
    if fixed_dates:
        print(f"Re-aggregating biometrics for {len(fixed_dates)} athlete-days...")
        for athlete_id, date_str in fixed_dates:
            # Fetch current biometrics for that day to preserve other metrics
            res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).eq("date", date_str).single().execute()
            if res.data:
                b = res.data
                payload = DailyBiometrics(
                    date=datetime.fromisoformat(date_str).date(),
                    source=b.get("hrv_source") or "whoop",
                    hrv_rmssd=float(b["hrv_rmssd"]) if b.get("hrv_rmssd") is not None else None,
                    resting_hr=b.get("resting_hr"),
                    sleep_duration_min=None, # Trigger re-aggregation
                    sleep_score=b.get("sleep_score"),
                    sleep_deep_pct=float(b["sleep_deep_pct"]) if b.get("sleep_deep_pct") is not None else None,
                    sleep_rem_pct=float(b["sleep_rem_pct"]) if b.get("sleep_rem_pct") is not None else None,
                    sleep_light_pct=float(b["sleep_light_pct"]) if b.get("sleep_light_pct") is not None else None,
                    sleep_awake_pct=float(b["sleep_awake_pct"]) if b.get("sleep_awake_pct") is not None else None,
                    sleep_bedtime=None,
                    sleep_wakeup=None,
                    skin_temp_deviation=float(b["skin_temp_deviation"]) if b.get("skin_temp_deviation") is not None else None,
                    spo2_pct=float(b["spo2_pct"]) if b.get("spo2_pct") is not None else None,
                    recovery_score=b.get("recovery_score")
                )
                process_and_save_biometrics(payload, athlete_id, db)
        print("Re-aggregation complete.")
    else:
        print("No re-aggregation needed.")

    print("--- Cleanup Complete ---")

if __name__ == "__main__":
    cleanup_sleep_data()
