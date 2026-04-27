#!/usr/bin/env python3
"""
seed_whoop_data.py
------------------
Ingests historical WHOOP CSV exports into the local Supabase instance
for the "Sean Balbale" athlete profile.

Tables populated:
  - biometrics     <- physiological_cycles.csv + sleeps.csv
  - workouts       <- workouts.csv
  - tss_history    <- derived from workouts (activity strain -> TSS proxy)
                     with rolling CTL/ATL/TSB

Usage (from repo root, with Supabase running locally):
  python scripts/seed_whoop_data.py

Requires:
  pip install supabase python-dotenv
"""

import csv
import os
import sys
import math
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client, Client

# -- Config ------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
WHOOP_DIR = REPO_ROOT / "docs" / "whoop files"
ENV_PATH  = REPO_ROOT / "backend" / ".env"

PHYS_CSV   = WHOOP_DIR / "physiological_cycles.csv"
SLEEP_CSV  = WHOOP_DIR / "sleeps.csv"
WORKOUT_CSV= WHOOP_DIR / "workouts.csv"

TARGET_DISPLAY_NAME = "Sean Balbale"

# TSS estimation constants
# WHOOP Strain 0-21 -> TSS proxy via a simple quadratic mapping.
STRAIN_TO_TSS_COEFF = 150 / (21 ** 2)   # approx 0.34

# PMC decay constants (standard 42d CTL / 7d ATL)
CTL_DECAY = math.exp(-1 / 42)
ATL_DECAY = math.exp(-1 / 7)

# Supabase service-role key env var name
SERVICE_KEY_VAR = "SUPABASE_SERVICE_ROLE_KEY"


# -- Helpers ------------------------------------------------------------------

def load_env() -> dict:
    load_dotenv(ENV_PATH)
    url = os.getenv("SUPABASE_URL")
    key = os.getenv(SERVICE_KEY_VAR) or os.getenv("SUPABASE_KEY")
    if not url or not key:
        sys.exit(f"[ERROR] Missing SUPABASE_URL or key in {ENV_PATH}")
    return {"url": url, "key": key}


def parse_ts(value: str) -> datetime | None:
    if not value or value.strip() == "":
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def to_float(value: str) -> float | None:
    try:
        v = float(value.strip())
        return v if not math.isnan(v) else None
    except (ValueError, AttributeError):
        return None


def to_int(value: str) -> int | None:
    f = to_float(value)
    return int(round(f)) if f is not None else None


def strain_to_tss(strain: float | None) -> float:
    if strain is None or strain <= 0:
        return 0.0
    return round(STRAIN_TO_TSS_COEFF * (strain ** 2), 2)


def map_activity(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("run", "jog", "track", "5k", "10k", "marathon")):
        return "run"
    if any(k in n for k in ("cycl", "bike", "bik", "row", "rowing", "spin")):
        return "bike"
    if any(k in n for k in ("swim",)):
        return "swim"
    if any(k in n for k in ("strength", "lift", "weight", "gym", "crossfit")):
        return "strength"
    return "other"


# -- Main ingestion steps -----------------------------------------------------

def resolve_athlete_id(db: Client) -> str:
    res = db.table("athletes").select("id, display_name").execute()
    for row in res.data:
        if TARGET_DISPLAY_NAME.lower() in (row.get("display_name") or "").lower():
            print(f"[OK] Found athlete: {row['display_name']} -> {row['id']}")
            return row["id"]
    names = [r.get("display_name") for r in res.data]
    sys.exit(f"[ERROR] Could not find athlete '{TARGET_DISPLAY_NAME}'. Found: {names}")


def ingest_biometrics(db: Client, athlete_id: str):
    print("\n[INFO] Ingesting biometrics ...")

    # Build sleep stages
    sleep_detail = {}
    with open(SLEEP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("Cycle start time") or "").strip()
            if not key: continue
            asleep = to_float(row.get("Asleep duration (min)", ""))
            awake  = to_float(row.get("Awake duration (min)", ""))
            total  = (asleep or 0) + (awake or 0)
            def pct(v): return round(v / total * 100, 1) if (v and total) else None
            sleep_detail[key] = {
                "deep_pct":  pct(to_float(row.get("Deep (SWS) duration (min)", ""))),
                "rem_pct":   pct(to_float(row.get("REM duration (min)", ""))),
                "light_pct": pct(to_float(row.get("Light sleep duration (min)", ""))),
                "awake_pct": pct(awake),
                "bedtime":   row.get("Sleep onset", "").strip() or None,
                "wakeup":    row.get("Wake onset",  "").strip() or None,
            }

    # Deduplicate by date: keep the one with a non-null recovery score
    date_map = {}
    with open(PHYS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cycle_start = (row.get("Cycle start time") or "").strip()
            ts_start = parse_ts(cycle_start)
            if not ts_start: continue
            
            record_date = ts_start.date().isoformat()
            recovery = to_int(row.get("Recovery score %", ""))
            
            # If we already have a record for this date and it has recovery, skip if this one is empty
            if record_date in date_map and recovery is None:
                continue

            detail = sleep_detail.get(cycle_start, {})
            record = {
                "athlete_id":         athlete_id,
                "date":               record_date,
                "hrv_rmssd":          to_float(row.get("Heart rate variability (ms)", "")),
                "hrv_source":         "whoop",
                "resting_hr":         to_int(row.get("Resting heart rate (bpm)", "")),
                "sleep_duration_min": to_int(row.get("Asleep duration (min)", "")),
                "sleep_score":        to_int(row.get("Sleep performance %", "")),
                "sleep_deep_pct":     detail.get("deep_pct"),
                "sleep_rem_pct":      detail.get("rem_pct"),
                "sleep_light_pct":    detail.get("light_pct"),
                "sleep_awake_pct":    detail.get("awake_pct"),
                "sleep_bedtime":      detail.get("bedtime") or row.get("Sleep onset", "").strip() or None,
                "sleep_wakeup":       detail.get("wakeup")  or row.get("Wake onset",  "").strip() or None,
                "skin_temp_deviation":to_float(row.get("Skin temp (celsius)", "")),
                "spo2_pct":           to_float(row.get("Blood oxygen %", "")),
                "recovery_score":     recovery,
            }
            date_map[record_date] = record

    records = list(date_map.values())
    if not records:
        print("[!] No biometric records found.")
        return

    CHUNK = 200
    total_upserted = 0
    for i in range(0, len(records), CHUNK):
        chunk = records[i:i+CHUNK]
        chunk_clean = [{k: v for k, v in r.items() if v is not None} for r in chunk]
        db.table("biometrics").upsert(chunk_clean, on_conflict="athlete_id,date").execute()
        total_upserted += len(chunk_clean)

    print(f"[OK] Upserted {total_upserted} deduplicated biometric records.")


def ingest_workouts(db: Client, athlete_id: str) -> dict[date, float]:
    print("\n[INFO] Ingesting workouts ...")
    daily_tss = defaultdict(float)
    records = []
    
    # We also need to deduplicate workout external_ids if WHOOP has duplicates
    seen_ids = set()

    with open(WORKOUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w_start_raw = (row.get("Workout start time") or "").strip()
            w_end_raw   = (row.get("Workout end time")   or "").strip()
            ts_start = parse_ts(w_start_raw)
            ts_end   = parse_ts(w_end_raw)
            if not ts_start or not ts_end: continue

            ext_id = f"whoop_{w_start_raw.replace(' ', 'T').replace(':', '-')}"
            if ext_id in seen_ids: continue
            seen_ids.add(ext_id)

            activity = (row.get("Activity name") or "Activity").strip()
            strain   = to_float(row.get("Activity Strain", ""))
            tss_val  = strain_to_tss(strain)
            
            records.append({
                "athlete_id":  athlete_id,
                "source":      "whoop",
                "external_id": ext_id,
                "sport":       map_activity(activity),
                "title":       activity,
                "started_at":  ts_start.isoformat(),
                "ended_at":    ts_end.isoformat(),
                "avg_hr":      to_int(row.get("Average HR (bpm)", "")),
                "max_hr":      to_int(row.get("Max HR (bpm)", "")),
                "tss":         tss_val if tss_val > 0 else None,
            })
            daily_tss[ts_start.date()] += tss_val

    if not records:
        print("[!] No workout records found.")
        return daily_tss

    CHUNK = 200
    total_upserted = 0
    for i in range(0, len(records), CHUNK):
        chunk = records[i:i+CHUNK]
        chunk_clean = [{k: v for k, v in r.items() if v is not None} for r in chunk]
        db.table("workouts").upsert(chunk_clean, on_conflict="source,external_id").execute()
        total_upserted += len(chunk_clean)

    print(f"[OK] Upserted {total_upserted} workout records.")
    return daily_tss


def ingest_tss_history(db: Client, athlete_id: str, daily_tss: dict[date, float]):
    print("\n[INFO] Computing & ingesting TSS history (PMC) ...")
    if not daily_tss: return

    all_dates = sorted(daily_tss.keys())
    start_date, end_date = all_dates[0], all_dates[-1]
    ctl, atl = 0.0, 0.0
    records = []
    current = start_date
    while current <= end_date:
        tss = daily_tss.get(current, 0.0)
        ctl = ctl * CTL_DECAY + tss * (1 - CTL_DECAY)
        atl = atl * ATL_DECAY + tss * (1 - ATL_DECAY)
        records.append({
            "athlete_id": athlete_id,
            "date":       current.isoformat(),
            "daily_tss":  round(tss, 2),
            "ctl":        round(ctl, 2),
            "atl":        round(atl, 2),
            "tsb":        round(ctl - atl, 2),
        })
        current += timedelta(days=1)

    CHUNK = 200
    total_upserted = 0
    for i in range(0, len(records), CHUNK):
        chunk = records[i:i+CHUNK]
        db.table("tss_history").upsert(chunk, on_conflict="athlete_id,date").execute()
        total_upserted += len(chunk)

    print(f"[OK] Upserted {total_upserted} TSS history records.")
    if records:
        l = records[-1]
        print(f"    Latest PMC -> CTL: {l['ctl']:.1f} | ATL: {l['atl']:.1f} | TSB: {l['tsb']:.1f}")


def main():
    print("=" * 60)
    print("  ASTRAPE - WHOOP Data Ingestion Script")
    print("=" * 60)
    cfg = load_env()
    db: Client = create_client(cfg["url"], cfg["key"])
    athlete_id = resolve_athlete_id(db)
    ingest_biometrics(db, athlete_id)
    daily_tss = ingest_workouts(db, athlete_id)
    ingest_tss_history(db, athlete_id, daily_tss)
    print("\n[OK] Ingestion complete.")

if __name__ == "__main__":
    main()
