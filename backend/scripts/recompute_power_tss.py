"""
Re-score power-based workout TSS with each athlete's profile FTP, then rebuild their PMC.

Until fix/tss-profile-ftp, every synced ride (and erg piece scored from power) used a
hardcoded FTP of 250 W: WorkoutPayload.ftp_at_time defaulted to 250 and no sync source set
it. This recomputes TSS for every workout with power data the same way process_and_save_workout
now does (profile FTP; bike: normalized power; row: average power x 1.12, only when the row has
no HR zones, as in the live path), then rebuilds CTL/ATL/TSB and daily strain.

Workouts without power, and athletes without an FTP, are left alone.

Usage (from backend/):
  python scripts/recompute_power_tss.py                 # dry run, all athletes
  python scripts/recompute_power_tss.py --athlete-id <uuid>
  python scripts/recompute_power_tss.py --apply         # write changes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dependencies import get_admin_db  # noqa: E402
from app.services.algorithms import compute_tss_power, normalize_rowing_watts  # noqa: E402
from app.services.processing import (  # noqa: E402
    _fetch_all_rows,
    recalculate_tss_history,
    refresh_all_daily_strain_sync,
    workout_ftp,
)


def new_tss(row: dict, ftp: int) -> float | None:
    """The TSS process_and_save_workout gives this stored workout now, if it's power-scored."""
    secs = row.get("duration_seconds") or 0
    if not secs:
        return None
    if row.get("sport") == "bike" and (row.get("norm_power_w") or 0) > 0:
        return compute_tss_power(secs, row["norm_power_w"], ftp)
    has_zones = any(row.get(f"hr_zone_{i}_pct") is not None for i in range(1, 6))
    if row.get("sport") == "row" and (row.get("avg_power_w") or 0) > 0 and not has_zones:
        return compute_tss_power(secs, int(normalize_rowing_watts(row["avg_power_w"])), ftp)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--athlete-id")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()
    db = get_admin_db()

    q = db.table("athletes").select("id,display_name,ftp_watts")
    athletes = (q.eq("id", args.athlete_id) if args.athlete_id else q).execute().data or []
    for a in athletes:
        ftp = workout_ftp(None, a.get("ftp_watts"))
        if not ftp:
            print(f"{a['id']} {a.get('display_name')!r}: no FTP, skipped")
            continue
        rows = _fetch_all_rows(
            lambda: db.table("workouts")
            .select("id,sport,duration_seconds,norm_power_w,avg_power_w,tss,"
                    "hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct")
            .eq("athlete_id", a["id"])
            .order("started_at")
        )
        changes = []
        for r in rows:
            t = new_tss(r, ftp)
            if t is None:
                continue
            t = round(float(t), 2)
            if abs(float(r.get("tss") or 0) - t) >= 0.01:
                changes.append((r["id"], float(r.get("tss") or 0), t))
        before = sum(c[1] for c in changes)
        after = sum(c[2] for c in changes)
        last = (
            db.table("tss_history").select("date,ctl").eq("athlete_id", a["id"]).order("date", desc=True).limit(1).execute().data
            or [{}]
        )[0]
        print(
            f"{a['id']} {a.get('display_name')!r} FTP {ftp}: {len(changes)} workouts change, "
            f"TSS {before:.0f} -> {after:.0f}; CTL now {last.get('ctl')} ({last.get('date')})"
        )
        if not args.apply or not changes:
            continue
        for wid, _old, t in changes:
            db.table("workouts").update({"tss": t}).eq("id", wid).execute()
        recalculate_tss_history(a["id"], db)
        refresh_all_daily_strain_sync(db, a["id"])
        last = (
            db.table("tss_history").select("date,ctl").eq("athlete_id", a["id"]).order("date", desc=True).limit(1).execute().data
            or [{}]
        )[0]
        print(f"   applied; CTL now {last.get('ctl')} ({last.get('date')})")
    if not args.apply:
        print("dry run: nothing written (pass --apply)")


if __name__ == "__main__":
    main()
