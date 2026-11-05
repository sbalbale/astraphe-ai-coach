"""
Recompute planned sessions' target TSS from their blocks (coach_tools.planned_tss).

The coach used to store planned TSS as the whole duration at one fixed IF per focus zone, and
never recomputed it when it edited a session, so stored values drifted from the blocks shown
(a 60-min 55% / 65% FTP ride showed 73 instead of ~39). Sessions whose value already matches
are left alone.

Usage (from backend/):
  python scripts/recompute_planned_tss.py                 # dry run, all athletes
  python scripts/recompute_planned_tss.py --athlete-id <uuid>
  python scripts/recompute_planned_tss.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dependencies import get_admin_db  # noqa: E402
from app.services.coach_tools import planned_tss  # noqa: E402
from app.services.processing import _fetch_all_rows  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--athlete-id")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()
    db = get_admin_db()

    def query():
        q = db.table("training_plans").select(
            "id,athlete_id,planned_date,title,sport,duration_min,primary_zone,target_tss,structure"
        )
        if args.athlete_id:
            q = q.eq("athlete_id", args.athlete_id)
        return q.order("planned_date")

    changes: dict[str, list[tuple[dict, int]]] = {}
    for r in _fetch_all_rows(query):
        if not r.get("duration_min"):
            continue
        new = int(round(planned_tss(r.get("structure"), r.get("duration_min"), r.get("primary_zone"))))
        if new != int(r.get("target_tss") or 0):
            changes.setdefault(r["athlete_id"], []).append((r, new))

    for aid, rows in changes.items():
        print(f"\n{aid}: {len(rows)} sessions, planned TSS {sum(int(r.get('target_tss') or 0) for r, _ in rows)} -> {sum(n for _, n in rows)}")
        for r, new in rows[-8:]:
            print(f"   {r['planned_date']} {r['title']!r} {r['duration_min']}m: {r.get('target_tss')} -> {new}")
        if args.apply:
            for r, new in rows:
                db.table("training_plans").update({"target_tss": new}).eq("id", r["id"]).execute()
            print("   applied")
    if not changes:
        print("nothing to change")
    elif not args.apply:
        print("\ndry run: nothing written (pass --apply)")


if __name__ == "__main__":
    main()
