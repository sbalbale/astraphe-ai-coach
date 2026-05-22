import sys
import os
import asyncio
from datetime import datetime, date

# Add the parent directory to sys.path so we can import from 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.models.workout import WorkoutPayload
from app.models.biometrics import DailyBiometrics
from app.services.processing import process_and_save_workout, process_and_save_biometrics, recalculate_tss_history

async def reprocess_athlete(athlete_id: str):
    db = get_admin_db()
    print(f"--- Starting Reprocessing for Athlete: {athlete_id} ---")

    # 1. Reprocess Workouts
    print("Reprocessing Workouts...")
    workouts_res = db.table("workouts").select("*").eq("athlete_id", athlete_id).order("started_at").execute()
    if workouts_res.data:
        print(f"Found {len(workouts_res.data)} workouts.")
        for w in workouts_res.data:
            payload = WorkoutPayload(
                source=w["source"],
                external_id=w["external_id"],
                sport=w["sport"],
                started_at=w["started_at"],
                ended_at=w["ended_at"],
                duration_seconds=w["duration_seconds"],
                distance_m=w["distance_m"],
                norm_power_w=w["norm_power_w"],
                avg_hr=w["avg_hr"],
                max_hr=w["max_hr"],
                avg_pace_sec_km=w["avg_pace_sec_km"],
                tss=None, # Force recalculation from zones if possible
                title=w["title"],
                hr_zone_0_pct=w.get("hr_zone_0_pct"),
                hr_zone_1_pct=w.get("hr_zone_1_pct"),
                hr_zone_2_pct=w.get("hr_zone_2_pct"),
                hr_zone_3_pct=w.get("hr_zone_3_pct"),
                hr_zone_4_pct=w.get("hr_zone_4_pct"),
                hr_zone_5_pct=w.get("hr_zone_5_pct")
            )
            # Skip per-workout TSS recalc; we rebuild once at the end (step 3).
            await process_and_save_workout(payload, athlete_id, db, skip_tss_recalc=True)
        print("Workouts reprocessed.")
    else:
        print("No workouts found.")

    # 2. Reprocess Biometrics
    print("Reprocessing Biometrics...")
    biometrics_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date").execute()
    if biometrics_res.data:
        print(f"Found {len(biometrics_res.data)} biometric days.")
        for b in biometrics_res.data:
            payload = DailyBiometrics(
                date=b["date"],
                source=b.get("hrv_source") or "whoop",
                hrv_rmssd=float(b["hrv_rmssd"]) if b.get("hrv_rmssd") is not None else None,
                resting_hr=b.get("resting_hr"),
                # DO NOT pass sleep_duration_min, bedtime, or wakeup.
                # This prevents the feedback loop where aggregated daily totals 
                # are saved back as individual periods.
                sleep_duration_min=None,
                sleep_score=b.get("sleep_score"),
                sleep_deep_pct=float(b["sleep_deep_pct"]) if b.get("sleep_deep_pct") is not None else None,
                sleep_rem_pct=float(b["sleep_rem_pct"]) if b.get("sleep_rem_pct") is not None else None,
                sleep_light_pct=float(b["sleep_light_pct"]) if b.get("sleep_light_pct") is not None else None,
                sleep_awake_pct=float(b["sleep_awake_pct"]) if b.get("sleep_awake_pct") is not None else None,
                sleep_bedtime=None,
                sleep_wakeup=None,
                skin_temp=float(b["skin_temp"]) if b.get("skin_temp") is not None else None,
                spo2_pct=float(b["spo2_pct"]) if b.get("spo2_pct") is not None else None,
                recovery_score=b.get("recovery_score")
            )
            process_and_save_biometrics(payload, athlete_id, db)
        print("Biometrics reprocessed.")
    else:
        print("No biometrics found.")

    # 3. Final PMC Recalculation (just to be safe)
    print("Final PMC recalculation...")
    recalculate_tss_history(athlete_id, db)
    
    print(f"--- Reprocessing Complete for Athlete: {athlete_id} ---")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reprocess_athlete_data.py <athlete_id>")
        sys.exit(1)
    
    target_id = sys.argv[1]
    asyncio.run(reprocess_athlete(target_id))
