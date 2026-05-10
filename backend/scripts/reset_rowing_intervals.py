"""
One-off: reset Strava-linked rowing workouts for interval re-ingest (see strava.reset_rowing_intervals).

Clears intervals when intervals_source is laps or stream_derived (stream_derived was
previously not reset). Does not run Strava backfill — run that or reprocess_strava_rowing_intervals separately.
"""
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.strava import reset_rowing_intervals


async def main() -> None:
    db = get_admin_db()
    n = await reset_rowing_intervals(db)
    print(f"reset_rowing_intervals updated {n} workout(s)")


if __name__ == "__main__":
    asyncio.run(main())
