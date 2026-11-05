"""
One-off reprocess after the data-pipeline fixes (fix/tss-profile-ftp, fix/data-pipeline).

Per athlete:
  1. Garmin multisport parents stored as one workout are split into their Garmin legs (the
     parent is deleted; Strava copies of the legs fold into the Garmin rows).
  2. Garmin on-water rows stored as sport "other" (title "... Rowing") become "row".
  3. Full reprocess in dependency order (processing.reprocess_athlete_metrics): every workout's
     TSS / strain with the anchors in effect on its date, then CTL/ATL/TSB, then each day's
     sleep, recovery and readiness, then daily strain.

The default is a dry run that changes nothing and reports, per athlete: the multisport parents
and rowing rows it would fix, the power / pace TSS changes, how many workouts are stuck at TSS
0, and CTL on a few dates before vs after the TSS changes.

Usage (from backend/):
  python scripts/reprocess_data_fixes.py                     # dry run, all athletes
  python scripts/reprocess_data_fixes.py --athlete-id <uuid>
  python scripts/reprocess_data_fixes.py --apply [--athlete-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dependencies import get_admin_db  # noqa: E402
from app.services.algorithms import compute_ctl  # noqa: E402
from app.services.anchor_history import local_day, rescore_tss  # noqa: E402
from app.services.processing import _fetch_all_rows, reprocess_athlete_metrics  # noqa: E402

CTL_DATES = ("2026-08-31", "2026-09-30", "2026-10-31")


def multisport_parents(db, athlete_id: str) -> list[dict]:
    res = (
        db.table("workouts")
        .select("id,title,started_at,garmin_activity_id,tss")
        .eq("athlete_id", athlete_id)
        .not_.is_("garmin_activity_id", "null")
        .ilike("title", "%multisport%")
        .execute()
    )
    return list(res.data or [])


def rowing_as_other(db, athlete_id: str) -> list[dict]:
    res = (
        db.table("workouts")
        .select("id,title,started_at")
        .eq("athlete_id", athlete_id)
        .eq("sport", "other")
        .ilike("title", "%rowing%")
        .execute()
    )
    return list(res.data or [])


def ctl_preview(db, athlete_id: str, offset: int | None, tss_changes: dict[str, float]) -> dict[str, tuple[float, float]]:
    """CTL on CTL_DATES and today, with stored TSS vs with the proposed changes."""
    rows = _fetch_all_rows(
        lambda: db.table("workouts").select("id,started_at,tss").eq("athlete_id", athlete_id).order("started_at")
    )
    if not rows:
        return {}
    before, after = defaultdict(float), defaultdict(float)
    for r in rows:
        d = local_day(r["started_at"], offset)
        t = float(r.get("tss") or 0)
        before[d] += t
        after[d] += tss_changes.get(r["id"], t)
    start = min(before)
    today = date.today()
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    ctl_b = compute_ctl(np.array([before.get(d, 0.0) for d in days]))
    ctl_a = compute_ctl(np.array([after.get(d, 0.0) for d in days]))
    idx = {d.isoformat(): i for i, d in enumerate(days)}
    out = {}
    for d in (*CTL_DATES, today.isoformat()):
        if d in idx:
            out[d] = (round(float(ctl_b[idx[d]]), 1), round(float(ctl_a[idx[d]]), 1))
    return out


async def split_parents(db, athlete_id: str, parents: list[dict]) -> int:
    from app.services import garmin

    client = await asyncio.to_thread(garmin.get_client_for_athlete, athlete_id, db)
    if client is None:
        print("   no Garmin client; multisport left as is")
        return 0
    legs_saved = 0
    for p in parents:
        legs = await garmin.split_multisport(client, db, athlete_id, p["garmin_activity_id"])
        for leg in legs:
            ok, _ = await garmin._save_one_activity(client, leg, athlete_id, db)
            legs_saved += int(bool(ok))
            await asyncio.sleep(garmin.GARMIN_REQUEST_GAP_S)
        print(f"   split {p['title']!r} ({p['started_at'][:10]}) into {len(legs)} new leg(s)")
    await asyncio.to_thread(garmin.persist_session, db, athlete_id, client)
    return legs_saved


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--athlete-id")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--skip-multisport", action="store_true", help="don't split multisport (no Garmin calls)")
    args = ap.parse_args()
    db = get_admin_db()

    q = db.table("athletes").select("id,display_name,timezone_offset_min")
    athletes = (q.eq("id", args.athlete_id) if args.athlete_id else q).execute().data or []
    for a in athletes:
        aid = a["id"]
        parents = multisport_parents(db, aid)
        rowing = rowing_as_other(db, aid)
        changes = rescore_tss(db, aid, apply=False)
        zero = (
            db.table("workouts").select("id", count="exact").eq("athlete_id", aid).eq("tss", 0)
            .not_.is_("hr_zone_1_pct", "null").execute().count
        )
        print(f"\n{aid} {a.get('display_name')!r}")
        for p in parents:
            print(f"   multisport parent: {p['title']!r} {p['started_at'][:10]} tss {p.get('tss')}")
        print(f"   rowing stored as other: {len(rowing)}")
        print(
            f"   power/pace TSS changes: {len(changes)} workouts, "
            f"{sum(c[1] for c in changes):.0f} -> {sum(c[2] for c in changes):.0f}"
        )
        print(f"   workouts with HR zones stuck at TSS 0: {zero}")
        for d, (b, af) in ctl_preview(db, aid, a.get("timezone_offset_min"), {c[0]: c[2] for c in changes}).items():
            print(f"   CTL {d}: {b} -> {af}")
        if not args.apply:
            continue
        if parents and not args.skip_multisport:
            await split_parents(db, aid, parents)
        for r in rowing:
            db.table("workouts").update({"sport": "row"}).eq("id", r["id"]).execute()
        counts = await reprocess_athlete_metrics(aid, db)
        print(f"   applied: reprocessed {counts}")
    if not args.apply:
        print("\ndry run: nothing written (pass --apply)")


if __name__ == "__main__":
    asyncio.run(main())
