"""
Recompute workouts.hr_zone_*_pct (and TSS/strain when HR-based) from stored HR streams
using the athlete's current zone model (get_athlete_zones / compute_zone_distribution).

Usage:
  python scripts/recalculate_athlete_hr_zones_from_streams.py "Sean Balbale"

Requires backend/.env with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

load_dotenv(REPO_ROOT / "backend" / ".env")

from app.services.algorithms import compute_hrss_from_zones, compute_strain_score
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services.processing import recalculate_tss_history
from app.services.strava import (  # noqa: E402
    _hr_stream_zone_dist_to_workout_columns,
    _load_stored_streams_dict,
)


def main() -> int:
    display_name = sys.argv[1] if len(sys.argv) > 1 else "Sean Balbale"
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in backend/.env")
        return 1

    db = create_client(url, key)

    res = db.table("athletes").select("*").eq("display_name", display_name).limit(5).execute()
    rows = list(res.data or []) if res is not None else []
    if not rows:
        res2 = (
            db.table("athletes")
            .select("*")
            .ilike("display_name", f"%{display_name}%")
            .limit(10)
            .execute()
        )
        rows = list(res2.data or []) if res2 is not None else []

    if not rows:
        print(f"No athlete matching display_name={display_name!r}")
        return 1
    if len(rows) > 1:
        exact = [r for r in rows if (r.get("display_name") or "").strip().lower() == display_name.strip().lower()]
        athlete = exact[0] if exact else rows[0]
        if len(rows) > 1 and not exact:
            print(f"Warning: multiple matches; using first: {athlete.get('display_name')!r}")
    else:
        athlete = rows[0]
    athlete_id = athlete["id"]
    print(f"athlete_id={athlete_id} name={display_name!r}")

    streams_res = (
        db.table("activity_streams").select("workout_id").eq("athlete_id", athlete_id).execute()
    )
    wids = [r["workout_id"] for r in (streams_res.data or [])]
    print(f"activity_streams rows: {len(wids)}")

    zones_def = get_athlete_zones(athlete)
    updated = 0
    skipped_no_hr = 0

    for wid in wids:
        streams = _load_stored_streams_dict(db, str(wid))
        hr_raw = (streams.get("heartrate") or {}).get("data", [])
        if not hr_raw:
            skipped_no_hr += 1
            continue

        hr_stream = [int(float(x)) for x in hr_raw if x is not None]
        if not hr_stream:
            skipped_no_hr += 1
            continue

        wres = (
            db.table("workouts")
            .select(
                "id,sport,duration_seconds,tss,hr_zone_1_pct,hr_zone_2_pct,hr_zone_3_pct,hr_zone_4_pct,hr_zone_5_pct"
            )
            .eq("id", wid)
            .limit(1)
            .execute()
        )
        rows_w = list(wres.data or []) if wres is not None else []
        if not rows_w:
            continue
        w = rows_w[0]

        zone_dist = compute_zone_distribution(hr_stream, zones_def)
        col_updates = _hr_stream_zone_dist_to_workout_columns(zone_dist)
        if not col_updates:
            continue

        update_payload: dict = dict(col_updates)
        dur = int(w.get("duration_seconds") or 0)
        sport = str(w.get("sport") or "other")

        if dur > 0:
            merged_pct: dict[int, float] = {}
            for z in range(1, 6):
                key = f"hr_zone_{z}_pct"
                raw = update_payload.get(key, w.get(key))
                merged_pct[z] = float(raw or 0)

            zone_minutes = {z: (merged_pct[z] / 100.0) * (dur / 60.0) for z in range(1, 6)}
            max_hr = int(athlete.get("max_hr") or 0)
            resting_hr = int(athlete.get("resting_hr") or 0)
            threshold_hr = int(athlete.get("threshold_hr") or 0)
            if (
                max_hr > resting_hr
                and threshold_hr > resting_hr
                and any(merged_pct.values())
            ):
                new_tss = compute_hrss_from_zones(
                    zone_minutes=zone_minutes,
                    max_hr=max_hr,
                    resting_hr=resting_hr,
                    threshold_hr=threshold_hr,
                    sport=sport,
                    gender=str(athlete.get("gender") or "male"),
                    threshold_hr_source=athlete.get("threshold_hr_source"),
                    hr_zone_method=athlete.get("hr_zone_method"),
                )
                update_payload["tss"] = new_tss
            update_payload["strain_score"] = compute_strain_score(zone_minutes, sport=sport)

        db.table("workouts").update(update_payload).eq("id", wid).execute()
        updated += 1

    print(f"updated_workouts={updated} skipped_no_heartrate_stream={skipped_no_hr}")

    print("Recalculating tss_history (PMC)...")
    recalculate_tss_history(athlete_id, db)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
