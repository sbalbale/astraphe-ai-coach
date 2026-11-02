"""Backfill the sleep-stage timeline (hypnogram) from Garmin for one athlete.

Fetches Garmin's get_sleep_data() for each day in the range, turns `sleepLevels`
into stage segments and stores them in `sleep_stage_segments` (idempotent: a
re-run replaces that athlete+date+garmin rows). Days Garmin returns no levels
for are left untouched. Only the sleep endpoint is called, one request per day.

Usage:
  cd backend && .venv\\Scripts\\python scripts/backfill_sleep_stages.py <athlete_uuid> [--days N]
  cd backend && .venv\\Scripts\\python scripts/backfill_sleep_stages.py <athlete_uuid> --from 2026-10-01 --to 2026-10-31
  cd backend && .venv\\Scripts\\python scripts/backfill_sleep_stages.py --from-env [--days N]

--days counts back from today (default 14). --from-env uses TEST_ATHLETE_ID from .env.
Uses the service-role DB and the athlete's stored Garmin session, so it needs a real
(not placeholder) Garmin token in oauth_tokens. Add --dry-run to print without saving.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Ensure backend is on PYTHONPATH when run as scripts/backfill_sleep_stages.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.dependencies import get_admin_db  # noqa: E402
from app.services.garmin import (  # noqa: E402
    get_client_for_athlete,
    parse_sleep_stage_segments,
    save_sleep_stage_segments,
)

# Gentle on Garmin: one call per day with a short pause between them.
_PAUSE_SECONDS = 1.0


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("athlete_id", nargs="?", help="athletes.id (UUID)")
    ap.add_argument("--from-env", action="store_true", help="use TEST_ATHLETE_ID from .env")
    ap.add_argument("--days", type=int, default=14, help="days back from today (default 14)")
    ap.add_argument("--from", dest="start", type=_parse_day, help="first day, YYYY-MM-DD")
    ap.add_argument("--to", dest="end", type=_parse_day, help="last day, YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, do not save")
    args = ap.parse_args()

    athlete_id = settings.TEST_ATHLETE_ID if args.from_env else args.athlete_id
    if not athlete_id:
        ap.error("pass an athlete UUID or --from-env (needs TEST_ATHLETE_ID)")
    end = args.end or date.today()
    start = args.start or (end - timedelta(days=max(args.days, 1) - 1))
    if start > end:
        ap.error("--from must not be after --to")

    db = get_admin_db()
    client = get_client_for_athlete(athlete_id, db)
    if client is None:
        print(f"[sleep_stages] could not restore a Garmin session for athlete_id={athlete_id}")
        return 1

    saved_days = 0
    day = start
    while day <= end:
        cdate = day.isoformat()
        try:
            sleep = client.get_sleep_data(cdate)
        except Exception as exc:  # network / auth / rate limit: keep going, report at the end
            print(f"[sleep_stages] {cdate}: Garmin request failed: {exc}")
            day += timedelta(days=1)
            time.sleep(_PAUSE_SECONDS)
            continue

        segments = parse_sleep_stage_segments(sleep)
        if not segments:
            print(f"[sleep_stages] {cdate}: no sleep levels returned, skipped")
        elif args.dry_run:
            print(f"[sleep_stages] {cdate}: {len(segments)} segments (dry run, not saved)")
        else:
            count = save_sleep_stage_segments(athlete_id, db, day, segments)
            saved_days += 1
            print(f"[sleep_stages] {cdate}: saved {count} segments")
        day += timedelta(days=1)
        time.sleep(_PAUSE_SECONDS)

    print(f"[sleep_stages] done: {saved_days} night(s) saved for {start} -> {end}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
