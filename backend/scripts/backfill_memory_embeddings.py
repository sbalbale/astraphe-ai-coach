"""
Backfill missing vector embeddings for legacy coach memories.

This script finds rows in `coach_memories` where `embedding` is NULL, generates an
embedding from `content` using the configured Gemini embedding model, and writes
the embedding back to the row.

Usage:
  cd backend && .venv\\Scripts\\python scripts/backfill_memory_embeddings.py --dry-run
  cd backend && .venv\\Scripts\\python scripts/backfill_memory_embeddings.py --from-env
  cd backend && .venv\\Scripts\\python scripts/backfill_memory_embeddings.py --athlete-id <uuid>

Notes:
  - Uses service role DB client (no user JWT), so it can update rows regardless of RLS.
  - Requires GEMINI_API_KEY and SUPABASE_* env vars (backend/.env is loaded by Settings).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Ensure backend is on PYTHONPATH when run as scripts/backfill_memory_embeddings.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.dependencies import get_admin_db  # noqa: E402
from app.services.memory import _extract_embedding  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill coach_memories.embedding where NULL.")
    p.add_argument("--athlete-id", help="Limit to one athlete_id (UUID).", default=None)
    p.add_argument(
        "--from-env",
        action="store_true",
        help="Use TEST_ATHLETE_ID from backend/.env as the athlete filter.",
    )
    p.add_argument("--batch-size", type=int, default=100, help="Rows per batch, default 100.")
    p.add_argument("--max-rows", type=int, default=0, help="Stop after N updates (0 = no limit).")
    p.add_argument(
        "--sleep",
        type=float,
        default=0.05,
        help="Seconds to sleep between embedding calls (helps avoid API bursts).",
    )
    p.add_argument("--dry-run", action="store_true", help="Print what would be updated; no writes.")
    return p.parse_args()


def _select_batch(db, *, athlete_id: str | None, batch_size: int) -> list[dict]:
    q = (
        db.table("coach_memories")
        .select("id, athlete_id, content, created_at")
        .is_("embedding", "null")
        .order("created_at", desc=False)
        .limit(batch_size)
    )
    if athlete_id:
        q = q.eq("athlete_id", athlete_id)
    res = q.execute()
    return res.data or []


def _update_embedding(db, *, memory_id: str, embedding: list[float], dry_run: bool) -> None:
    if dry_run:
        return
    db.table("coach_memories").update({"embedding": embedding}).eq("id", memory_id).execute()


async def _run(*, athlete_id: str | None, batch_size: int, max_rows: int, sleep_s: float, dry_run: bool) -> None:
    db = get_admin_db()

    print("=" * 72)
    print("backfill_memory_embeddings.py")
    print(f"  model: {settings.GEMINI_EMBEDDING_MODEL}")
    if athlete_id:
        print(f"  athlete_id: {athlete_id}")
    print(f"  batch_size: {batch_size}")
    print(f"  max_rows: {max_rows if max_rows > 0 else 'unlimited'}")
    print(f"  dry_run: {dry_run}")
    print("=" * 72)

    updated = skipped = errors = 0
    seen_ids: set[str] = set()
    t0 = time.monotonic()

    while True:
        if max_rows > 0 and updated >= max_rows:
            break

        rows = await asyncio.to_thread(_select_batch, db, athlete_id=athlete_id, batch_size=batch_size)
        if not rows:
            break

        progressed_this_batch = False
        for r in rows:
            if max_rows > 0 and updated >= max_rows:
                break

            mid = str(r.get("id") or "")
            content = (r.get("content") or "").strip()
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)
            if not mid or not content:
                skipped += 1
                continue

            try:
                await asyncio.sleep(max(0.0, sleep_s))
                emb = await asyncio.to_thread(_extract_embedding, content)
                if not emb:
                    errors += 1
                    print(f"  ERROR: empty embedding for id={mid}")
                    continue
                await asyncio.to_thread(_update_embedding, db, memory_id=mid, embedding=emb, dry_run=dry_run)
                updated += 1
                progressed_this_batch = True
                if updated <= 20 or updated % 50 == 0:
                    print(f"  {'WOULD UPDATE' if dry_run else 'UPDATED'} {updated} id={mid} len={len(emb)}")
            except Exception as e:
                errors += 1
                print(f"  ERROR id={mid}: {e!r}")

        # In dry-run, don't loop forever on the same missing rows.
        if dry_run:
            break
        # Safety: if we didn't process anything new, stop to avoid an infinite loop.
        if not progressed_this_batch:
            break

    dt = time.monotonic() - t0
    print()
    print("Summary")
    print(f"  updated: {updated}")
    print(f"  skipped: {skipped}")
    print(f"  errors: {errors}")
    print(f"  elapsed: {dt:.1f}s")


def main() -> None:
    args = _parse_args()
    batch_size = max(1, min(int(args.batch_size), 1000))
    sleep_s = max(0.0, float(args.sleep))

    athlete_id = (args.athlete_id or "").strip() or None
    if args.from_env:
        athlete_id = settings.TEST_ATHLETE_ID or None

    asyncio.run(
        _run(
            athlete_id=athlete_id,
            batch_size=batch_size,
            max_rows=int(args.max_rows),
            sleep_s=sleep_s,
            dry_run=bool(args.dry_run),
        )
    )


if __name__ == "__main__":
    main()

