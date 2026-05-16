"""One-off WHOOP backfill via service role DB (no user JWT).

Usage:
  cd backend && .venv\\Scripts\\python scripts/run_whoop_backfill.py <athlete_uuid> [--days N]
  cd backend && .venv\\Scripts\\python scripts/run_whoop_backfill.py --from-env [--days N]

Uses TEST_ATHLETE_ID from .env when --from-env is passed.

"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure backend is on PYTHONPATH when run as scripts/run_whoop_backfill.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.dependencies import get_admin_db  # noqa: E402
from app.services import whoop  # noqa: E402
from app.services.whoop_backfill import backfill_historical_data  # noqa: E402


async def _refresh_whoop_token(db, athlete_id: str, refresh_token: str) -> str | None:
    try:
        token_data = await whoop.refresh_oauth_token(refresh_token)
    except Exception as e:
        print(f"[whoop.backfill.cli] Refresh request failed: {e}")
        return None
    new_access = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token") or refresh_token
    if not new_access:
        print("[whoop.backfill.cli] Refresh response missing access_token")
        return None
    db.table("oauth_tokens").update(
        {"access_token": new_access, "refresh_token": new_refresh}
    ).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()
    print("[whoop.backfill.cli] Persisted refreshed WHOOP access token")
    return new_access


async def _run(athlete_id: str, days: int) -> None:
    db = get_admin_db()
    tok = (
        db.table("oauth_tokens")
        .select("access_token", "refresh_token")
        .eq("athlete_id", athlete_id)
        .eq("provider", "whoop")
        .maybe_single()
        .execute()
    )
    row = tok.data if tok else None
    access_token = row.get("access_token") if row else None
    refresh_token = row.get("refresh_token") if row else None
    if not access_token:
        print(f"[whoop.backfill.cli] No WHOOP access_token for athlete_id={athlete_id}")
        raise SystemExit(1)
    if refresh_token:
        new_access = await _refresh_whoop_token(db, athlete_id, refresh_token)
        access_token = new_access or access_token
    print(f"[whoop.backfill.cli] Starting backfill athlete_id={athlete_id} days={days}")
    await backfill_historical_data(athlete_id, access_token, db, days)
    print("[whoop.backfill.cli] Done.")


def main() -> None:
    p = argparse.ArgumentParser(description="Run WHOOP historical backfill.")
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
    d = max(1, min(int(args.days), 365))
    aid = settings.TEST_ATHLETE_ID if args.from_env else args.athlete_id
    db = get_admin_db()
    if not aid:
        rows = getattr(
            db.table("oauth_tokens").select("athlete_id").eq("provider", "whoop").limit(1).execute(),
            "data",
            None,
        ) or []
        if rows:
            aid = str(rows[0]["athlete_id"])
            print("[whoop.backfill.cli] No athlete argument; using WHOOP-connected athlete_id=" + aid)
    if not aid:
        print("Provide athlete UUID, pass --from-env with TEST_ATHLETE_ID set, or connect WHOOP.")
        raise SystemExit(2)
    asyncio.run(_run(aid, d))


if __name__ == "__main__":
    main()
