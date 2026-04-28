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


def parse_ts(ts_str: str, tz_str: str = None) -> datetime | None:
    if not ts_str or ts_str.strip() == "":
        return None
    
    # Try parsing format with seconds
    dt = None
    try:
        dt = datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(ts_str.strip(), "%Y-%m-%d")
        except ValueError:
            return None

    # Handle timezone if provided (e.g. "UTC-04:00")
    if tz_str and "UTC" in tz_str:
        try:
            offset_str = tz_str.replace("UTC", "").strip()
            if offset_str:
                sign = 1 if offset_str[0] == '+' else -1
                parts = offset_str[1:].split(':')
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                tz = timezone(timedelta(hours=sign*h, minutes=sign*m))
                return dt.replace(tzinfo=tz)
        except Exception:
            pass
            
    # Fallback to local system time
    return dt.astimezone()


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


def hr_zones_to_tss(duration_min: float, zones: dict[int, int]) -> float:
    """
    Standard hrTSS calculation based on time in zones.
    Weights: Z1=0.45, Z2=0.65, Z3=0.85, Z4=1.05, Z5=1.25
    """
    weights = {1: 0.45, 2: 0.65, 3: 0.85, 4: 1.05, 5: 1.25}
    weighted_hours = 0
    for z, pct in zones.items():
        if pct:
            weighted_hours += (duration_min / 60) * (pct / 100) * weights.get(z, 0)
    return round(weighted_hours * 100, 2)


def calculate_astrape_sleep_need(baseline_min, previous_strain, current_debt_min):
    # Astrape Need = Baseline + (Strain * 1.8) + Current Debt
    # We cap the strain impact to 2 hours (120 mins)
    strain_impact = min(120, (previous_strain or 0) * 1.8)
    return int(round(baseline_min + strain_impact + (current_debt_min or 0)))

def calculate_astrape_sleep_score(duration_min, sleep_need_min, rem_pct, deep_pct):
    if not duration_min or not sleep_need_min: return 0
    
    # Fulfillment score (70%)
    fulfillment_score = min(100, (duration_min / sleep_need_min) * 100)
    
    # Quality: REM + Deep % (goal: 45%)
    qual_pct = (rem_pct or 0) + (deep_pct or 0)
    qual_score = min(100, (qual_pct / 45) * 100)
    
    return int(round(fulfillment_score * 0.7 + qual_score * 0.3))


def calculate_astrape_recovery_score(hrv, rhr, sleep_score, hrv_baseline=55, rhr_baseline=52):
    if hrv is None or rhr is None or sleep_score is None: return None
    # HRV score (45%)
    hrv_ratio = hrv / (hrv_baseline or 50)
    hrv_score = min(100, max(0, hrv_ratio * 75))
    # RHR score (25%)
    rhr_diff = (rhr_baseline or 60) - rhr
    rhr_score = min(100, max(0, 50 + (rhr_diff * 5)))
    # Sleep contrib (30%)
    return int(round(hrv_score * 0.45 + rhr_score * 0.25 + sleep_score * 0.3))


def map_activity(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("run", "jog", "track", "5k", "10k", "marathon")):
        return "run"
    if any(k in n for k in ("cycl", "bike", "bik", "spin")):
        return "bike"
    if any(k in n for k in ("row", "rowing")):
        return "rowing"
    if any(k in n for k in ("swim",)):
        return "swim"
    if any(k in n for k in ("strength", "lift", "weight", "gym", "crossfit")):
        return "gym"
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

    # Deduplicate by date and calculate rolling debt
    all_phys = []
    with open(PHYS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            all_phys.append(row)
    
    # Sort chronologically to calculate rolling debt
    all_phys.sort(key=lambda r: (r.get("Cycle start time") or "").strip())

    date_map = {}
    current_rolling_debt = 0 # In minutes

    for i, row in enumerate(all_phys):
        cycle_start = (row.get("Cycle start time") or "").strip()
        tz_str = (row.get("Cycle timezone") or "").strip()
        ts_start = parse_ts(cycle_start, tz_str)
        if not ts_start: continue
        
        record_date = ts_start.date().isoformat()
        recovery = to_int(row.get("Recovery score %", ""))
        
        # Use previous day's strain for current sleep need
        prev_strain = to_float(all_phys[i-1].get("Day Strain", 0)) if i > 0 else 0
        
        s_need = calculate_astrape_sleep_need(480, prev_strain, current_rolling_debt)
        s_actual = to_int(row.get("Asleep duration (min)", 0)) or 0
        
        # Update rolling debt for NEXT day (cap at 120m to prevent runaway)
        current_rolling_debt = min(120, max(0, s_need - s_actual))

        detail = sleep_detail.get(cycle_start, {})
        s_score = calculate_astrape_sleep_score(
            s_actual,
            s_need,
            detail.get("rem_pct"),
            detail.get("deep_pct")
        )
        
        r_score = calculate_astrape_recovery_score(
            to_float(row.get("Heart rate variability (ms)", "")),
            to_int(row.get("Resting heart rate (bpm)", "")),
            s_score
        )

        record = {
            "athlete_id":         athlete_id,
            "date":               record_date,
            "hrv_rmssd":          to_float(row.get("Heart rate variability (ms)", "")),
            "hrv_source":         "whoop",
            "resting_hr":         to_int(row.get("Resting heart rate (bpm)", "")),
            "day_strain":         to_float(row.get("Day Strain", 0)),
            "sleep_duration_min": s_actual,
            "sleep_score":        to_int(row.get("Sleep performance %", "")),
            "sleep_debt_min":     current_rolling_debt, # This is the debt for the NEXT day
            "sleep_need_min":     s_need,
            "astrape_sleep_score": s_score,
            "astrape_recovery_score": r_score,
            "sleep_deep_pct":     detail.get("deep_pct"),
            "sleep_rem_pct":      detail.get("rem_pct"),
            "sleep_light_pct":    detail.get("light_pct"),
            "sleep_awake_pct":    detail.get("awake_pct"),
            "sleep_bedtime":      parse_ts(detail.get("bedtime") or row.get("Sleep onset", "").strip(), tz_str).isoformat() if (detail.get("bedtime") or row.get("Sleep onset")) else None,
            "sleep_wakeup":       parse_ts(detail.get("wakeup")  or row.get("Wake onset",  "").strip(), tz_str).isoformat() if (detail.get("wakeup") or row.get("Wake onset")) else None,
            "skin_temp_deviation":to_float(row.get("Skin temp (celsius)", "")),
            "spo2_pct":           to_float(row.get("Blood oxygen %", "")),
            "recovery_score":     recovery,
        }
        # If we have multiple entries for same date, latest one (sorted) wins
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
            tz_str      = (row.get("Cycle timezone")     or "").strip()
            ts_start = parse_ts(w_start_raw, tz_str)
            ts_end   = parse_ts(w_end_raw, tz_str)
            if not ts_start or not ts_end: continue

            ext_id = f"whoop_{w_start_raw.replace(' ', 'T').replace(':', '-')}"
            if ext_id in seen_ids: continue
            seen_ids.add(ext_id)

            activity = (row.get("Activity name") or "Activity").strip()
            strain   = to_float(row.get("Activity Strain", ""))
            
            # Parse zones for TSS calculation
            zones = {
                1: to_int(row.get("HR Zone 1 %", "")),
                2: to_int(row.get("HR Zone 2 %", "")),
                3: to_int(row.get("HR Zone 3 %", "")),
                4: to_int(row.get("HR Zone 4 %", "")),
                5: to_int(row.get("HR Zone 5 %", "")),
            }
            
            duration_min = (ts_end - ts_start).total_seconds() / 60
            
            # Use zone-based TSS if available, fallback to strain-based
            if any(v is not None for v in zones.values()):
                tss_val = hr_zones_to_tss(duration_min, zones)
            else:
                tss_val = strain_to_tss(strain)
            
            record = {
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
                "astrape_strain_score": int(min(100, round((tss_val / 150) * 100))) if tss_val > 0 else 0,
                "hr_zone_1_pct": zones[1],
                "hr_zone_2_pct": zones[2],
                "hr_zone_3_pct": zones[3],
                "hr_zone_4_pct": zones[4],
                "hr_zone_5_pct": zones[5],
            }
            records.append(record)
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
