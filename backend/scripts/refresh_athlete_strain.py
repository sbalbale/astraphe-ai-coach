"""Recompute biometrics.strain_score from workout HR zones for one athlete (fast)."""
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.processing import refresh_all_daily_strain_sync


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python refresh_athlete_strain.py <athlete_id>")
        sys.exit(1)
    athlete_id = sys.argv[1]
    db = get_admin_db()
    counts = refresh_all_daily_strain_sync(db, athlete_id)
    print(f"Refreshed strain for {counts['days']} day(s) (athlete_id={athlete_id})")


if __name__ == "__main__":
    main()
