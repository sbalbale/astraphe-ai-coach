"""Throwaway: dump raw Garmin get_sleep_data() JSON for one night + summarise sleepLevels.

Usage: python scripts/dump_garmin_sleep.py [YYYY-MM-DD] [athlete_id] [out_path]
Restores the session exactly like get_client_for_athlete (oauth_tokens -> restore_session).
Output contains personal data: write it outside the repo and do not commit it.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if "__file__" in globals():  # local run; in the prod pod (piped via stdin) cwd already has `app`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")
    except ImportError:
        pass

from app.dependencies import get_admin_db  # noqa: E402
from app.services.garmin import PROVIDER, get_client_for_athlete  # noqa: E402

cdate = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()
athlete_id = sys.argv[2] if len(sys.argv) > 2 else None
out = Path(sys.argv[3] if len(sys.argv) > 3 else "garmin_sleep_dump.json")

db = get_admin_db()
if not athlete_id:
    rows = db.table("oauth_tokens").select("athlete_id").eq("provider", PROVIDER).execute().data
    if not rows:
        sys.exit("no garmin oauth_tokens rows")
    athlete_id = rows[0]["athlete_id"]
    print(f"using athlete_id={athlete_id} ({len(rows)} garmin athletes)")

client = get_client_for_athlete(athlete_id, db)
if client is None:
    sys.exit("could not restore garmin session")

data = client.get_sleep_data(cdate)  # the single Garmin call; nothing else is hit
out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
print(f"wrote {out}")

print("top-level keys:", sorted(data.keys()))
dto = data.get("dailySleepDTO") or {}
print("dailySleepDTO keys:", sorted(dto.keys()))
for k in ("calendarDate", "sleepStartTimestampGMT", "sleepEndTimestampGMT", "sleepStartTimestampLocal",
          "sleepEndTimestampLocal", "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds",
          "awakeSleepSeconds", "unmeasurableSleepSeconds", "sleepTimeSeconds"):
    print(f"  {k} = {dto.get(k)!r}")

lv = data.get("sleepLevels")
print("sleepLevels type:", type(lv).__name__, "len:", len(lv) if lv is not None else None)
if lv:
    print("first 3:", json.dumps(lv[:3]))
    print("last 2:", json.dumps(lv[-2:]))
    print("segment keys:", sorted({k for s in lv for k in s}))
    tot = defaultdict(float)
    fmt_seen = set()
    prev_end = None
    gaps = 0
    for s in lv:
        st, en = s.get("startGMT"), s.get("endGMT")
        fmt_seen.add(type(st).__name__ + ":" + str(st)[-6:])
        a = datetime.fromisoformat(str(st).replace("Z", "")); b = datetime.fromisoformat(str(en).replace("Z", ""))
        tot[s.get("activityLevel")] += (b - a).total_seconds()
        if prev_end is not None and a != prev_end:
            gaps += 1
            print(f"  gap/overlap: prev_end={prev_end} next_start={a}")
        prev_end = b
    print("activityLevel -> summed seconds:", dict(sorted(tot.items(), key=lambda kv: str(kv[0]))))
    print("non-contiguous boundaries:", gaps)
    print("timestamp format samples:", sorted(fmt_seen)[:5])
