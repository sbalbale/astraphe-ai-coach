"""Clean up an athlete's coach memories: absolute dates and no duplicates.

Older memories were saved with relative dates ("52 km row this Saturday") and no
event_date, so weeks later the coach reads them as upcoming. This sends the athlete's
note memories (with the day each was noted) to the analysis model once, which returns
each memory rewritten with absolute dates plus an event_date, and flags duplicates /
superseded notes to drop. Race memories (memory_type='race') are left alone.

Usage:
  cd backend && .venv\\Scripts\\python scripts/normalize_coach_memories.py <athlete_uuid> [--dry-run]

Uses the service-role DB. Prints every change; --dry-run prints without writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.genai import types  # noqa: E402

from app.config import settings  # noqa: E402
from app.dependencies import get_admin_db  # noqa: E402
from app.services import memory  # noqa: E402

PROMPT = """\
You are cleaning up an athlete's saved coaching notes. Today is {today}.
Each note has an id, the date it was noted, and its text. Relative words in a note
("Saturday", "this weekend", "next month") are relative to the day it was noted.

For every note return an object:
  {{"id": "<id>", "fact": "<rewritten note, max 150 chars>", "event_date": "YYYY-MM-DD" or null, "drop": true|false}}
- Rewrite relative dates as absolute dates (e.g. "52 km row on 2026-10-24"). Keep everything else.
- event_date: the date of the dated event the note is about, else null.
- drop: true for a note that repeats a newer note, or is superseded by a newer one
  (e.g. "52k scheduled for Saturday" once a later note says it was completed). Keep the newest.

Notes (id · noted on · text):
{notes}

Return ONLY the JSON array, one object per note.
JSON array:"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("athlete_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = get_admin_db()
    rows = [
        m for m in memory.list_coach_memories(args.athlete_id, db=db, limit=200)
        if (m.get("memory_type") or "note") == "note"
    ]
    if not rows:
        print("[memories] nothing to clean")
        return 0
    today = memory._athlete_local_today(args.athlete_id, db)
    notes = "\n".join(
        f"{m['id']} · {str(m.get('created_at') or '')[:10]} · {m.get('content')}" for m in rows
    )
    model = settings.GEMINI_ANALYSIS_MODEL or settings.GEMINI_MODEL
    response = memory._llm_client.models.generate_content(
        model=model,
        contents=PROMPT.format(today=today.isoformat(), notes=notes),
        config=types.GenerateContentConfig(max_output_tokens=8192, temperature=0.0),
    )
    text = (getattr(response, "text", None) or "").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        print("[memories] model returned no JSON array:\n" + text[:500])
        return 1
    items = json.loads(match.group())
    by_id = {str(m["id"]): m for m in rows}

    updated = dropped = 0
    for item in items:
        mid = str(item.get("id") or "")
        current = by_id.get(mid)
        if not current:
            continue
        if item.get("drop"):
            print(f"DROP   {mid} · {current.get('content')}")
            dropped += 1
            if not args.dry_run:
                memory._delete_memories(args.athlete_id, [mid], db)
            continue
        fact = str(item.get("fact") or "").strip()[:200]
        event_date = memory._parse_iso_date(item.get("event_date"))
        if not fact or (fact == current.get("content") and event_date == current.get("event_date")):
            continue
        print(f"UPDATE {mid} · {current.get('content')}\n    -> {fact}" + (f"  [event {event_date}]" if event_date else ""))
        updated += 1
        if not args.dry_run:
            payload = {"content": fact, "updated_at": datetime.now(timezone.utc).isoformat()}
            if fact != current.get("content"):
                payload["embedding"] = memory._extract_embedding(fact)
            if event_date:
                payload["event_date"] = event_date
            db.table("coach_memories").update(payload).eq("id", mid).eq("athlete_id", args.athlete_id).execute()

    print(f"[memories] {'would update' if args.dry_run else 'updated'} {updated}, "
          f"{'would drop' if args.dry_run else 'dropped'} {dropped} of {len(rows)} notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
