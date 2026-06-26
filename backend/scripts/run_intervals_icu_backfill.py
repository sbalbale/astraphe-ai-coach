"""One-off Intervals.icu backfill via service role DB (no user JWT).

Usage:
  cd backend && .venv\\Scripts\\python scripts/run_intervals_icu_backfill.py <athlete_uuid> [--days N]
  cd backend && .venv\\Scripts\\python scripts/run_intervals_icu_backfill.py --from-env [--days N]

Uses TEST_ATHLETE_ID from .env when --from-env is passed. If no athlete is
provided, uses the first Intervals.icu-connected athlete.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure backend is on PYTHONPATH when run as scripts/run_intervals_icu_backfill.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.dependencies import get_admin_db  # noqa: E402
from app.services.intervals_icu import PROVIDER, backfill_historical_data  # noqa: E402


async def _run(athlete_id: str, days: int) -> None:
    db = get_admin_db()
    tok = (
        db.table("oauth_tokens")
        .select("access_token, external_user_id")
        .eq("athlete_id", athlete_id)
        .eq("provider", PROVIDER)
        .maybe_single()
        .execute()
    )
    row = tok.data if tok else None
    api_key = row.get("access_token") if row else None
    intervals_athlete_id = row.get("external_user_id") if row else None
    if not api_key or not intervals_athlete_id:
        print(f"[intervals.backfill.cli] Intervals.icu not connected for athlete_id={athlete_id}")
        raise SystemExit(1)

    print(
        "[intervals.backfill.cli] Starting backfill "
        f"athlete_id={athlete_id} intervals_id={intervals_athlete_id} days={days}"
    )
    result = await backfill_historical_data(
        athlete_id,
        str(intervals_athlete_id),
        str(api_key),
        db,
        days,
    )
    print(f"[intervals.backfill.cli] Done. result={result}")


def _first_connected_athlete_id(db) -> str | None:
    rows = getattr(
        db.table("oauth_tokens")
        .select("athlete_id")
        .eq("provider", PROVIDER)
        .limit(1)
        .execute(),
        "data",
        None,
    ) or []
    if not rows:
        return None
    return str(rows[0]["athlete_id"])


def main() -> None:
    p = argparse.ArgumentParser(description="Run Intervals.icu historical backfill.")
    p.add_argument("athlete_id", nargs="?", help="athletes.id UUID (omit with --from-env)")
    p.add_argument(
        "--from-env",
        action="store_true",
        help="Use TEST_ATHLETE_ID from .env instead of positional athlete_id",
    )
    p.add_argument(
        "--days",
        type=int,
        default=90,
        help="Historical window (1–365), default 90",
    )
    args = p.parse_args()
    days = max(1, min(int(args.days), 365))
    athlete_id = settings.TEST_ATHLETE_ID if args.from_env else args.athlete_id
    db = get_admin_db()
    if not athlete_id:
        athlete_id = _first_connected_athlete_id(db)
        if athlete_id:
            print(
                "[intervals.backfill.cli] No athlete argument; using "
                f"Intervals.icu-connected athlete_id={athlete_id}"
            )
    if not athlete_id:
        print("Provide athlete UUID, pass --from-env with TEST_ATHLETE_ID set, or connect Intervals.icu.")
        raise SystemExit(2)

    asyncio.run(_run(str(athlete_id), days))


if __name__ == "__main__":
    main()
