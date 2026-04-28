import os
from datetime import date, datetime, timedelta
from supabase import create_client, Client

# Mock payload that looks like DailyBiometrics
class MockPayload:
    def __init__(self, **kwargs):
        self.date = kwargs.get('date')
        self.source = kwargs.get('source', 'whoop')
        self.hrv_rmssd = kwargs.get('hrv_rmssd')
        self.resting_hr = kwargs.get('resting_hr')
        self.sleep_duration_min = kwargs.get('sleep_duration_min')
        self.sleep_score = kwargs.get('sleep_score')
        self.sleep_deep_pct = kwargs.get('sleep_deep_pct')
        self.sleep_rem_pct = kwargs.get('sleep_rem_pct')
        self.sleep_light_pct = kwargs.get('sleep_light_pct')
        self.sleep_awake_pct = kwargs.get('sleep_awake_pct')
        self.sleep_bedtime = kwargs.get('sleep_bedtime')
        self.sleep_wakeup = kwargs.get('sleep_wakeup')
        self.is_nap = kwargs.get('is_nap', False)
        self.day_strain = kwargs.get('day_strain')
        self.skin_temp_deviation = kwargs.get('skin_temp_deviation')
        self.spo2_pct = kwargs.get('spo2_pct')

# I'll manually test the logic by calling the db directly or simulating the processing service
# Since I can't easily import the backend app code into this standalone script, 
# I will simulate the process_and_save_biometrics logic.

url = "http://127.0.0.1:57321"
key = "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
db: Client = create_client(url, key)

athlete_id = "52c00ba6-d91b-4eb3-b0ad-c533161da9bd"
test_date = date(2026, 4, 23)

def simulate_processing(payload):
    # This matches the logic I just implemented in processing.py
    
    # 1. Save Sleep Period
    if payload.sleep_duration_min is not None:
        session_data = {
            "athlete_id": athlete_id,
            "date": payload.date.isoformat(),
            "started_at": payload.sleep_bedtime.isoformat() if payload.sleep_bedtime else None,
            "ended_at": payload.sleep_wakeup.isoformat() if payload.sleep_wakeup else None,
            "duration_min": payload.sleep_duration_min,
            "score": payload.sleep_score,
            "deep_pct": payload.sleep_deep_pct,
            "rem_pct": payload.sleep_rem_pct,
            "light_pct": payload.sleep_light_pct,
            "awake_pct": payload.sleep_awake_pct,
            "is_nap": payload.is_nap,
            "source": payload.source,
            "external_id": f"test_{payload.source}_{payload.sleep_bedtime.timestamp() if payload.sleep_bedtime else payload.date.isoformat()}"
        }
        db.table("sleep_periods").upsert(session_data, on_conflict="source,external_id").execute()

    # 2. Aggregate
    all_periods = db.table("sleep_periods").select("*").eq("athlete_id", athlete_id).eq("date", payload.date.isoformat()).execute().data
    
    total_sleep = sum(p['duration_min'] for p in all_periods)
    print(f"Aggregated Duration for {payload.date}: {total_sleep} mins")
    
    # 3. Update Biometrics
    db.table("biometrics").upsert({
        "athlete_id": athlete_id,
        "date": payload.date.isoformat(),
        "sleep_duration_min": total_sleep,
        # ... other fields
    }).execute()

# 1. Simulate Main Sleep (7 hours)
main_sleep = MockPayload(
    date=test_date,
    sleep_duration_min=420,
    sleep_score=85,
    sleep_bedtime=datetime(2026, 4, 22, 22, 0),
    sleep_wakeup=datetime(2026, 4, 23, 6, 0),
    is_nap=False,
    deep_pct=20,
    rem_pct=25,
    light_pct=50,
    awake_pct=5
)
print("Processing Main Sleep...")
simulate_processing(main_sleep)

# 2. Simulate Nap (45 mins)
nap = MockPayload(
    date=test_date,
    sleep_duration_min=45,
    sleep_score=None,
    sleep_bedtime=datetime(2026, 4, 23, 14, 0),
    sleep_wakeup=datetime(2026, 4, 23, 14, 45),
    is_nap=True,
    deep_pct=10,
    rem_pct=5,
    light_pct=80,
    awake_pct=5
)
print("Processing Nap...")
simulate_processing(nap)

# 3. Check Final State
res = db.table("biometrics").select("sleep_duration_min").eq("athlete_id", athlete_id).eq("date", test_date.isoformat()).single().execute()
print(f"Final Biometrics Duration: {res.data['sleep_duration_min']} mins")

periods = db.table("sleep_periods").select("duration_min, is_nap").eq("athlete_id", athlete_id).eq("date", test_date.isoformat()).execute()
print(f"Individual Periods: {periods.data}")
