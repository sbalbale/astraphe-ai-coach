import sys
import os
import asyncio
from datetime import datetime, date

# Add the parent directory to sys.path so we can import from 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.processing import reprocess_athlete_metrics

async def reprocess_athlete(athlete_id: str):
    db = get_admin_db()
    print(f"--- Starting Reprocessing for Athlete: {athlete_id} ---")
    counts = await reprocess_athlete_metrics(athlete_id, db)
    print(f"Reprocessed {counts['workouts']} workouts, {counts['biometrics']} biometric days.")
    print(f"--- Reprocessing Complete for Athlete: {athlete_id} ---")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reprocess_athlete_data.py <athlete_id>")
        sys.exit(1)
    
    target_id = sys.argv[1]
    asyncio.run(reprocess_athlete(target_id))
