"""
Reprocess every Strava-linked workout already stored in Supabase.

Default (API mode): re-run full ``ingest_strava_activity`` for each distinct
``strava_activity_id`` (from ``workouts.strava_activity_id`` and ``source_ids.strava``).
Refetches activity detail, streams, laps, intervals, and updates ``activity_laps``.

DB-only mode (no Strava HTTP): recomputes rowing intervals/laps from
``raw_strava_payload`` + stored streams — same as reprocess_strava_rowing_intervals.py.

Env:
  ATHLETE_ID=<uuid>       Limit to one athlete (optional).
  DB_ONLY=1               Rowing intervals from DB payloads only (fast).
  REPROCESS_FORCE=1       With DB_ONLY: include rows that already have intervals.
  DRY_RUN=1               Print plan only; no writes / no Strava calls.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.dependencies import get_admin_db
from app.services.strava import (
    StravaRateLimitError,
    STRAVA_BACKFILL_REQUEST_GAP_S,
    STRAVA_RATE_LIMIT_COOLDOWN_S,
    get_valid_token,
    ingest_strava_activity,
    reprocess_rowing_intervals_from_stored_data,
)


def _parse_source_ids(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            out = json.loads(raw)
            return out if isinstance(out, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _strava_activity_ids_for_workout(row: dict) -> list[int]:
    ids: list[int] = []
    primary = row.get("strava_activity_id")
    if primary is not None:
        try:
            ids.append(int(primary))
        except (TypeError, ValueError):
            pass
    source_ids = _parse_source_ids(row.get("source_ids"))
    strava_part = source_ids.get("strava")
    if isinstance(strava_part, list):
        for item in strava_part:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                continue
    elif strava_part is not None:
        try:
            ids.append(int(strava_part))
        except (TypeError, ValueError):
            pass
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _intervals_missing(inv: object) -> bool:
    if inv is None:
        return True
    if isinstance(inv, list) and len(inv) == 0:
        return True
    if isinstance(inv, str) and inv.strip() in ("", "[]", "null"):
        return True
    return False


async def _reprocess_db_only(db, athlete_filter: str | None, force: bool, dry_run: bool) -> None:
    res = db.table("workouts").select("id, athlete_id, sport, intervals, raw_strava_payload").eq(
        "sport", "row"
    ).execute()
    rows = res.data or []
    candidates: list[str] = []
    for w in rows:
        wid = w.get("id")
        if not wid:
            continue
        if athlete_filter and str(w.get("athlete_id")) != athlete_filter:
            continue
        if not w.get("raw_strava_payload"):
            continue
        if force or _intervals_missing(w.get("intervals")):
            candidates.append(str(wid))

    print(f"DB-only rowing reprocess: {len(candidates)} workout(s)")
    if dry_run:
        for wid in candidates[:20]:
            print(f"  would reprocess {wid}")
        if len(candidates) > 20:
            print(f"  ... and {len(candidates) - 20} more")
        return

    ok = skip = err = 0
    for i, wid in enumerate(candidates, start=1):
        status, detail = await asyncio.to_thread(
            reprocess_rowing_intervals_from_stored_data, db, wid
        )
        print(f"  {i}/{len(candidates)} {wid} -> {status}: {detail}")
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            err += 1
    print(f"Summary: ok={ok} skip={skip} error={err}")


async def _reprocess_via_api(db, athlete_filter: str | None, dry_run: bool) -> None:
    query = (
        db.table("workouts")
        .select("id, athlete_id, strava_activity_id, source_ids, sport")
        .not_.is_("strava_activity_id", "null")
    )
    if athlete_filter:
        query = query.eq("athlete_id", athlete_filter)
    res = query.execute()
    rows = res.data or []

    by_athlete: dict[str, set[int]] = {}
    for row in rows:
        aid = row.get("athlete_id")
        if not aid:
            continue
        for sid in _strava_activity_ids_for_workout(row):
            by_athlete.setdefault(str(aid), set()).add(sid)

    total_acts = sum(len(v) for v in by_athlete.values())
    print(f"API re-ingest: {len(by_athlete)} athlete(s), {total_acts} distinct Strava activity id(s)")
    print(f"Gap between requests: {STRAVA_BACKFILL_REQUEST_GAP_S}s (Strava rate limits)")

    if dry_run:
        for aid, ids in by_athlete.items():
            print(f"  athlete {aid}: {len(ids)} activities")
        return

    ok = skip = err = rl = 0
    for a_idx, (athlete_id, activity_ids) in enumerate(sorted(by_athlete.items()), start=1):
        print("-" * 60)
        print(f"Athlete {a_idx}/{len(by_athlete)}: {athlete_id} ({len(activity_ids)} activities)")

        ath = (
            db.table("athletes")
            .select("strava_athlete_id")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        if not ath.data:
            print("  SKIP: athlete row missing")
            skip += len(activity_ids)
            continue
        owner_raw = ath.data.get("strava_athlete_id")
        if owner_raw is None:
            print("  SKIP: strava_athlete_id null")
            skip += len(activity_ids)
            continue
        try:
            owner = int(owner_raw)
        except (TypeError, ValueError):
            print(f"  SKIP: invalid strava_athlete_id={owner_raw!r}")
            skip += len(activity_ids)
            continue

        token = await get_valid_token(athlete_id, db)
        if not token:
            print("  SKIP: no Strava token")
            skip += len(activity_ids)
            continue

        sorted_ids = sorted(activity_ids, reverse=True)
        for i, activity_id in enumerate(sorted_ids, start=1):
            await asyncio.sleep(STRAVA_BACKFILL_REQUEST_GAP_S)
            rl_attempts = 0
            while rl_attempts < 6:
                try:
                    result = await ingest_strava_activity(
                        owner_strava_id=owner,
                        activity_id=activity_id,
                        db=db,
                        delay=True,
                        access_token=token,
                    )
                    if result:
                        ok += 1
                        print(f"  {i}/{len(sorted_ids)} activity {activity_id} -> ok")
                    else:
                        skip += 1
                        print(f"  {i}/{len(sorted_ids)} activity {activity_id} -> skip (no result)")
                    break
                except StravaRateLimitError as e:
                    wait = (
                        e.retry_after
                        if e.retry_after and e.retry_after > 0
                        else STRAVA_RATE_LIMIT_COOLDOWN_S
                    )
                    rl += 1
                    print(
                        f"  activity {activity_id} 429 — sleeping {wait}s "
                        f"(attempt {rl_attempts + 1}/6)"
                    )
                    await asyncio.sleep(wait)
                    rl_attempts += 1
                except Exception as e:
                    err += 1
                    print(f"  {i}/{len(sorted_ids)} activity {activity_id} -> error: {e!r}")
                    break
            else:
                err += 1
                print(f"  activity {activity_id} gave up after repeated 429s")

    print()
    print("Summary")
    print(f"  ingested ok: {ok}")
    print(f"  skipped: {skip}")
    print(f"  errors: {err}")
    print(f"  rate-limit waits: {rl}")


async def main() -> None:
    t0 = time.monotonic()
    athlete_filter = os.environ.get("ATHLETE_ID", "").strip() or None
    db_only = os.environ.get("DB_ONLY", "").strip().lower() in ("1", "true", "yes")
    force = os.environ.get("REPROCESS_FORCE", "").strip().lower() in ("1", "true", "yes")
    dry_run = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

    print("=" * 60)
    print("reprocess_strava_in_db.py")
    print(f"  mode: {'DB-only (rowing intervals)' if db_only else 'API full re-ingest'}")
    if athlete_filter:
        print(f"  ATHLETE_ID={athlete_filter}")
    if dry_run:
        print("  DRY_RUN=1")
    print("=" * 60)

    db = get_admin_db()
    if db_only:
        await _reprocess_db_only(db, athlete_filter, force, dry_run)
    else:
        await _reprocess_via_api(db, athlete_filter, dry_run)

    print(f"Done in {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
