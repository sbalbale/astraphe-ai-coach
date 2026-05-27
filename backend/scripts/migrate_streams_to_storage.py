#!/usr/bin/env python3
"""
Backfill activity_streams.time_series JSONB into Supabase Storage (gzip JSON).

Run from repo root with backend env loaded:
  cd backend && python scripts/migrate_streams_to_storage.py [--dry-run] [--limit N] [--athlete-id UUID]
"""
from __future__ import annotations

import argparse
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.dependencies import get_admin_db  # noqa: E402
from app.services import stream_storage  # noqa: E402


def _fetch_batch(db, *, athlete_id: str | None, limit: int, offset: int) -> list[dict]:
    q = (
        db.table("activity_streams")
        .select("workout_id, athlete_id, time_series, storage_path")
        .is_("storage_path", "null")
        .not_.is_("time_series", "null")
        .order("created_at")
        .range(offset, offset + limit - 1)
    )
    if athlete_id:
        q = q.eq("athlete_id", athlete_id)
    res = q.execute()
    return list(res.data or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate stream JSONB to Storage gzip blobs")
    parser.add_argument("--dry-run", action="store_true", help="List rows only, no upload")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all)")
    parser.add_argument("--athlete-id", type=str, default=None, help="Only this athlete")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    db = get_admin_db()
    processed = 0

    while True:
        batch_limit = args.batch_size
        if args.limit:
            remaining = args.limit - processed
            if remaining <= 0:
                break
            batch_limit = min(batch_limit, remaining)

        rows = _fetch_batch(
            db, athlete_id=args.athlete_id, limit=batch_limit, offset=0
        )
        if not rows:
            break

        for row in rows:
            workout_id = row["workout_id"]
            athlete_id = row["athlete_id"]
            ts = row.get("time_series")
            if not isinstance(ts, dict) or not ts:
                continue
            if args.dry_run:
                print(f"would migrate {athlete_id}/{workout_id}")
            else:
                path, byte_size = stream_storage.upload_time_series_gzip(
                    athlete_id, workout_id, ts
                )
                db.table("activity_streams").update(
                    {
                        "storage_path": path,
                        "byte_size": byte_size,
                        "content_encoding": stream_storage.CONTENT_ENCODING,
                        "time_series": None,
                    }
                ).eq("workout_id", workout_id).execute()
                print(f"migrated {path} ({byte_size} bytes)")
            processed += 1

        # Do not increment an offset here: each successful row updates `storage_path`
        # and would shift the remaining result set, causing skipped rows.

    print(f"done: {processed} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
