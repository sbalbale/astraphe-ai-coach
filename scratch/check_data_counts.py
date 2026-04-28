import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH  = REPO_ROOT / "backend" / ".env"

load_dotenv(ENV_PATH)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

db: Client = create_client(url, key)

athlete_id = "52c00ba6-d91b-4eb3-b0ad-c533161da9bd"

workouts = db.table("workouts").select("id").eq("athlete_id", athlete_id).execute()
biometrics = db.table("biometrics").select("id").eq("athlete_id", athlete_id).execute()
tss = db.table("tss_history").select("id").eq("athlete_id", athlete_id).execute()

print(f"Data for athlete {athlete_id}:")
print(f"Workouts: {len(workouts.data)}")
print(f"Biometrics: {len(biometrics.data)}")
print(f"TSS History: {len(tss.data)}")
