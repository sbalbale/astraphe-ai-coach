"""Auto-match past recorded workouts to planned sessions (one-off after linking ships).

For each workout in the range, completes the same-day planned session with the same sport
and a similar duration (the same rule as live syncs). Sessions already done, linked, or
where the athlete dismissed that workout are left alone, so re-running is safe.

Usage:
  cd backend && .venv\\Scripts\\python scripts/backfill_plan_matches.py <athlete_uuid> [--days N]
  cd backend && .venv\\Scripts\\python scripts/backfill_plan_matches.py --all [--days N]

--days counts back from today (default 60). --all runs every athlete with planned sessions.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies import get_admin_db  # noqa: E402
from app.services import plan_matching  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("athlete_id", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()
    if not args.athlete_id and not args.all:
        ap.error("give an athlete id or --all")

    db = get_admin_db()
    since = date.today() - timedelta(days=args.days)
    if args.all:
        rows = db.table("training_plans").select("athlete_id").gte("planned_date", since.isoformat()).execute().data or []
        athletes = sorted({r["athlete_id"] for r in rows})
    else:
        athletes = [args.athlete_id]

    total = 0
    for aid in athletes:
        n = plan_matching.backfill(db, aid, since)
        total += n
        print(f"{aid}: linked {n} session(s)")
    print(f"done: {total} session(s) linked across {len(athletes)} athlete(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
