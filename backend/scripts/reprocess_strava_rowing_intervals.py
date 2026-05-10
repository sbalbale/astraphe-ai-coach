"""
Recompute rowing intervals from data already in Supabase (no Strava API).

Uses ``workouts.raw_strava_payload``, ``activity_streams.time_series``, and
``activity_laps`` (else laps embedded in the payload). Sets ``intervals``,
``intervals_source``, ``strava_streams_fetched=true``, and HR zone % columns
when a heartrate stream exists.

By default processes ``sport=row`` workouts where ``intervals`` is null or an
empty list and ``raw_strava_payload`` is present (e.g. after reset_rowing_intervals).

Env:
  REPROCESS_WORKOUT_ID   If set, only this workout UUID (still must be row + payload).
  REPROCESS_FORCE=1     Recompute all row workouts with raw_strava_payload (even if intervals set).
"""
import asyncio
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.strava import reprocess_rowing_intervals_from_stored_data


def _intervals_missing(inv: object) -> bool:
    if inv is None:
        return True
    if isinstance(inv, list) and len(inv) == 0:
        return True
    if isinstance(inv, str) and inv.strip() in ("", "[]", "null"):
        return True
    return False


async def main() -> None:
    t0 = time.monotonic()
    force = os.environ.get("REPROCESS_FORCE", "").strip() in ("1", "true", "yes")
    single = os.environ.get("REPROCESS_WORKOUT_ID", "").strip()

    print("=" * 60)
    print("reprocess_strava_rowing_intervals.py")
    print("  DB-only — no Strava HTTP")
    if force:
        print("  REPROCESS_FORCE=1 — including workouts that already have intervals")
    if single:
        print(f"  REPROCESS_WORKOUT_ID={single}")
    print("=" * 60)

    db = get_admin_db()

    if single:
        print(f"[single] workout_id={single}")
        status, detail = await asyncio.to_thread(
            reprocess_rowing_intervals_from_stored_data, db, single
        )
        print(f"  -> {status}: {detail}")
        print(f"Done in {time.monotonic() - t0:.1f}s")
        return

    print("[1/2] Loading candidate workouts (sport=row)…")
    res = (
        db.table("workouts")
        .select("id, intervals, raw_strava_payload")
        .eq("sport", "row")
        .execute()
    )
    rows = res.data or []
    candidates: list[str] = []
    for w in rows:
        wid = w.get("id")
        if not wid:
            continue
        if not w.get("raw_strava_payload"):
            continue
        if force:
            candidates.append(str(wid))
            continue
        if _intervals_missing(w.get("intervals")):
            candidates.append(str(wid))

    print(f"       Row workouts in DB: {len(rows)}")
    print(f"       To reprocess: {len(candidates)}")

    if not candidates:
        print()
        print("Nothing to do. Tip: use REPROCESS_WORKOUT_ID or REPROCESS_FORCE=1")
        print(f"Finished in {time.monotonic() - t0:.1f}s")
        return

    print()
    print("[2/2] Reprocessing…")
    ok = skip = err = 0
    for i, wid in enumerate(candidates, start=1):
        status, detail = await asyncio.to_thread(
            reprocess_rowing_intervals_from_stored_data, db, wid
        )
        line = f"  {i}/{len(candidates)} {wid} -> {status}: {detail}"
        print(line)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            err += 1

    print()
    print("Summary")
    print(f"  ok: {ok}  skip: {skip}  error: {err}")
    print(f"Total wall time: {time.monotonic() - t0:.1f}s")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
