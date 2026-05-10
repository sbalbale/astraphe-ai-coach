"""
Strava backfill for athletes who have rowing workouts still pending detail ingest
(e.g. after reset_rowing_intervals: strava_streams_fetched = false).

Uses the same pipeline as OAuth callback backfill. Set STRAVA_BACKFILL_DAYS (default 90).
"""
import asyncio
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.strava import backfill_historical_data, get_valid_token


async def main() -> None:
    days = int(os.environ.get("STRAVA_BACKFILL_DAYS", "90"))
    t0 = time.monotonic()

    print("=" * 60)
    print("strava_backfill_pending.py")
    print(f"  STRAVA_BACKFILL_DAYS = {days}")
    print("  Query: sport=row, strava_streams_fetched=false")
    print("=" * 60)

    db = get_admin_db()
    print("[1/3] Loading pending rowing workouts from Supabase…")
    res = (
        db.table("workouts")
        .select("athlete_id, strava_activity_id")
        .eq("sport", "row")
        .eq("strava_streams_fetched", False)
        .execute()
    )
    rows = res.data or []
    with_strava = [r for r in rows if r.get("strava_activity_id") is not None]
    athlete_ids = list({r["athlete_id"] for r in with_strava})

    print(f"       Rows returned: {len(rows)}")
    print(f"       With strava_activity_id: {len(with_strava)}")
    print(f"       Distinct athletes to consider: {len(athlete_ids)}")

    if not athlete_ids:
        print()
        print("Nothing to do — no athletes with pending row Strava workouts.")
        print(f"Finished in {time.monotonic() - t0:.1f}s")
        return

    print()
    print(f"[2/3] Running Strava backfill for {len(athlete_ids)} athlete(s)…")
    print("       (Strava service also logs [strava.backfill] / [strava.ingest] lines)")
    print()

    ok = 0
    skipped = 0
    for i, aid in enumerate(athlete_ids, start=1):
        print("-" * 60)
        print(f"Athlete {i}/{len(athlete_ids)}: id={aid}")
        ath = (
            db.table("athletes")
            .select("strava_athlete_id")
            .eq("id", aid)
            .maybe_single()
            .execute()
        )
        if not ath.data:
            print("  SKIP: no athlete row")
            skipped += 1
            continue
        sid = ath.data.get("strava_athlete_id")
        if sid is None:
            print("  SKIP: strava_athlete_id is null")
            skipped += 1
            continue
        try:
            owner = int(sid)
        except (TypeError, ValueError):
            print(f"  SKIP: invalid strava_athlete_id={sid!r}")
            skipped += 1
            continue

        print(f"  Strava athlete id: {owner}")
        print("  Resolving Strava access token…")
        token = await get_valid_token(aid, db)
        if not token:
            print("  SKIP: no Strava token (connect Strava or refresh oauth_tokens)")
            skipped += 1
            continue
        print("  Token OK — starting backfill (this can take several minutes)…")

        t_ath = time.monotonic()
        await backfill_historical_data(aid, owner, token, db, days=days)
        print(f"  Backfill finished for this athlete in {time.monotonic() - t_ath:.1f}s")
        ok += 1

    print()
    print("[3/3] Summary")
    print(f"       Backfills completed: {ok}")
    print(f"       Skipped: {skipped}")
    print(f"Total wall time: {time.monotonic() - t0:.1f}s")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
