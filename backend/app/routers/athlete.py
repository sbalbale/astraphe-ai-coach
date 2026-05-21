from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import date, datetime, timedelta
from typing import Optional, List

import numpy as np

from app.models.athlete import AthleteState, AthleteProfileUpdate
from app.services.algorithms import compute_z_score
from app.services.hr_zones import athlete_dict_with_hr_zones, get_athlete_zones, optional_canonical_hr_zone_method
from app.services.resend_service import sync_marketing_contact
from app.dependencies import get_current_athlete, get_current_user_email, get_user_db, get_admin_db

router = APIRouter(prefix="/v1/athlete", tags=["Athlete"])

def _calc_biometrics_streak_days(bio_rows: list) -> int:
    """
    Calculates consecutive days of biometrics availability ending at the most recent date.
    Assumes `bio_rows` are ordered by date desc and contain a `date` field (ISO string).
    """
    if not bio_rows:
        return 0

    dates: list[date] = []
    for r in bio_rows:
        d = r.get("date")
        if not d:
            continue
        try:
            # Supabase can return YYYY-MM-DD or full ISO datetime strings
            dates.append(date.fromisoformat(str(d)[:10]))
        except Exception:
            continue

    if not dates:
        return 0

    # Ensure unique + sorted desc (db order should already be desc, but be defensive)
    uniq = sorted(set(dates), reverse=True)
    streak = 1
    for i in range(1, len(uniq)):
        if (uniq[i - 1] - uniq[i]).days == 1:
            streak += 1
        else:
            break
    return streak

@router.post("/onboard")
async def onboard_athlete(athlete_id: str = Depends(get_current_athlete), db = Depends(get_user_db)):
    """Seeds initial sample data for a newly registered athlete."""
    today = date.today()
    
    # Seed today's biometrics
    db.table("biometrics").upsert([{
        "athlete_id": athlete_id,
        "date": today.isoformat(),
        "hrv_rmssd": 78.0,
        "resting_hr": 52,
        "sleep_duration_min": 450,
        "sleep_score": 94,
        "recovery_score": 78,
        "spo2_pct": 98.0
    }]).execute()
    
    # Seed upcoming training plan
    plan_entries = [
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=1)).isoformat(), "sport": "Run", "title": "Easy Recovery Run", "description": "Aerobic base. Keep HR in Z2.", "duration_min": 45, "target_tss": 38, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=2)).isoformat(), "sport": "Bike", "title": "Threshold Intervals", "description": "5x8min @FTP. 3min recovery.", "duration_min": 90, "target_tss": 95, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=3)).isoformat(), "sport": "Run", "title": "Rest Day", "description": "Full recovery. Optional walk.", "duration_min": 0, "target_tss": 0, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=4)).isoformat(), "sport": "Run", "title": "Tempo Run", "description": "20min tempo in Z3-Z4.", "duration_min": 55, "target_tss": 68, "status": "planned"},
        {"athlete_id": athlete_id, "planned_date": (today + timedelta(days=5)).isoformat(), "sport": "Bike", "title": "Long Endurance Ride", "description": "Z2 only. High cadence focus.", "duration_min": 180, "target_tss": 95, "status": "planned"},
    ]
    db.table("training_plans").upsert(plan_entries).execute()
    
    return {"status": "success", "message": "Athlete onboarded with sample data"}



@router.get("/state", response_model=AthleteState)
async def get_athlete_state(athlete_id: str = Depends(get_current_athlete), db = Depends(get_user_db)):
    """
    Returns the athlete's current physiological state including computed CTL, ATL, TSB, and readiness score.
    """
    # Fetch athlete
    athlete_res = db.table("athletes").select("display_name").eq("id", athlete_id).execute()
    if not athlete_res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")
    display_name = athlete_res.data[0]["display_name"]
    
    # Fetch latest tss_history
    tss_res = db.table("tss_history").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    ctl, atl, tsb = 0.0, 0.0, 0.0
    if tss_res.data:
        tss = tss_res.data[0]
        ctl = tss.get("ctl") or 0.0
        atl = tss.get("atl") or 0.0
        tsb = tss.get("tsb") or 0.0

    # Fetch latest biometrics
    bio_res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    bio = bio_res.data[0] if bio_res.data else {}

    # Pull last ~30 biometrics rows (date asc) for HRV/RHR EWMA z-scores.
    # We want a stable rolling window; 30 samples is plenty for a span=7 EWMA.
    bio_window_res = (
        db.table("biometrics")
        .select("date,hrv_rmssd,resting_hr")
        .eq("athlete_id", athlete_id)
        .order("date", desc=True)
        .limit(30)
        .execute()
    )
    window_rows = list(reversed(bio_window_res.data or []))

    def _series(field: str) -> np.ndarray:
        vals: list[float] = []
        for r in window_rows:
            v = r.get(field)
            try:
                if v is None:
                    continue
                fv = float(v)
                if fv == 0:
                    continue
                vals.append(fv)
            except Exception:
                continue
        return np.array(vals, dtype=float) if vals else np.array([], dtype=float)

    hrv_series = _series("hrv_rmssd")
    rhr_series = _series("resting_hr")

    hrv_latest = bio.get("hrv_rmssd")
    rhr_latest = bio.get("resting_hr")

    hrv_z, hrv_base, hrv_sd = (
        compute_z_score(float(hrv_latest), hrv_series[:-1] if len(hrv_series) > 1 else hrv_series, span=7)
        if hrv_latest is not None and len(hrv_series) > 0
        else (None, None, None)
    )
    rhr_z, rhr_base, rhr_sd = (
        compute_z_score(float(rhr_latest), rhr_series[:-1] if len(rhr_series) > 1 else rhr_series, span=7)
        if rhr_latest is not None and len(rhr_series) > 0
        else (None, None, None)
    )

    # Calibration / history: compute consecutive-day biometrics streak up to ~2 months.
    # This is more meaningful than "account age" for model readiness.
    bio_hist_res = (
        db.table("biometrics")
        .select("date")
        .eq("athlete_id", athlete_id)
        .order("date", desc=True)
        .limit(70)
        .execute()
    )
    days_on_platform = _calc_biometrics_streak_days(bio_hist_res.data or [])

    return {
        "athlete_id": athlete_id,
        "display_name": display_name,
        "date": date.today(),
        "days_on_platform": int(days_on_platform),
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "hrv_rmssd": bio.get("hrv_rmssd"),
        "hrv_delta_7d": (float(hrv_latest) - float(hrv_base)) if (hrv_latest is not None and hrv_base is not None) else 0.0,
        "hrv_baseline_7d": hrv_base,
        "hrv_sd_7d": hrv_sd,
        "hrv_z": hrv_z,
        "resting_hr": bio.get("resting_hr"),
        "rhr_baseline_7d": rhr_base,
        "rhr_sd_7d": rhr_sd,
        "rhr_z": rhr_z,
        "sleep_hours": bio.get("sleep_duration_min", 0) / 60.0 if bio.get("sleep_duration_min") else None,
        "sleep_score": bio.get("sleep_score"),
        "sleep_debt_min": bio.get("sleep_debt_min"),
        "recovery_score": bio.get("recovery_score"),
        "readiness_score": bio.get("readiness_score") or 0,
        "readiness_label": "Optimal" if (bio.get("readiness_score") or 0) > 70 else "Moderate",
        "readiness_recommendation": "Calculated by Astrape Intelligence."
    }

@router.get("/metrics")
async def get_athlete_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    metrics: str = Query("ctl,atl,tsb", description="Comma-separated metrics to include"),
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Returns computed metrics over a date range."""
    start_date = start_date or (date.today() - timedelta(days=42))
    end_date = end_date or date.today()
    
    # Query recent tss_history
    tss_res = (
        db.table("tss_history")
        .select("date,daily_tss,ctl,atl,tsb")
        .eq("athlete_id", athlete_id)
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .order("date")
        .execute()
    )
    
    training_load_data = []
    for row in tss_res.data:
        d = date.fromisoformat(row["date"])
        training_load_data.append({
            # Keep ISO date for reliable client-side matching, plus a short label for charts.
            "date": row["date"],
            "day": d.strftime("%a"),
            "daily_tss": row.get("daily_tss") or 0,
            "ctl": row["ctl"] or 0,
            "atl": row["atl"] or 0,
            "tsb": row["tsb"] or 0
        })

    return {
        "athlete_id": athlete_id,
        "start_date": start_date,
        "end_date": end_date,
        "trainingLoadData": training_load_data,
        "paceData": [],
        "zoneData": []
    }

@router.get("/profile")
async def get_athlete_profile(
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Fetch current athlete physiological anchors."""
    try:
        res = db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute()
    except Exception:
        # Keep error surface clean; auth issues are handled in dependency.
        raise HTTPException(status_code=500, detail="Failed to load athlete profile")
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")
    return athlete_dict_with_hr_zones(res.data)


def _build_athlete_zones_update(payload: dict) -> dict:
    """
    Map PUT /zones JSON to athletes columns. Never includes `lthr` (GENERATED ALWAYS).
    Client may send `method` (mapped to hr_zone_method) or `lthr` (mapped to threshold_hr).
    Normalizes hr_zone_method values (e.g. max_hr_percent -> max_hr) for DB CHECK constraint.
    """
    if not isinstance(payload, dict):
        return {}
    out: dict = {}
    hm, m = payload.get("hr_zone_method"), payload.get("method")
    if hm is not None:
        out["hr_zone_method"] = hm
    elif m is not None:
        out["hr_zone_method"] = m
    for k in ("max_hr", "resting_hr"):
        if k in payload and payload[k] is not None:
            out[k] = payload[k]
    thr_raw = None
    if "lthr" in payload and payload.get("lthr") is not None:
        thr_raw = payload["lthr"]
    elif "threshold_hr" in payload and payload.get("threshold_hr") is not None:
        thr_raw = payload["threshold_hr"]
    if thr_raw is not None:
        try:
            tv = int(thr_raw)
            out["threshold_hr"] = tv
            if tv > 0:
                out["threshold_hr_source"] = "manual"
        except (TypeError, ValueError):
            pass
    if "hr_zone_method" in out and out["hr_zone_method"] is not None:
        try:
            canon = optional_canonical_hr_zone_method(out["hr_zone_method"])
            if canon is None:
                out.pop("hr_zone_method", None)
            else:
                out["hr_zone_method"] = canon
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="hr_zone_method must be lthr, hrr, or max_hr",
            )
    return out


@router.get("/zones")
async def get_zones(
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the athlete's current HR zone definitions."""
    res = (
        db.table("athletes")
        .select("lthr, threshold_hr, max_hr, resting_hr, hr_zone_method")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    athlete = res.data or {}
    zones = get_athlete_zones(athlete)
    return {
        "zones": [
            {"zone": z.zone, "name": z.name, "min_bpm": z.min_bpm, "max_bpm": z.max_bpm}
            for z in zones
        ],
        "anchors": {
            "lthr": athlete.get("lthr") or athlete.get("threshold_hr"),
            "max_hr": athlete.get("max_hr"),
            "resting_hr": athlete.get("resting_hr"),
            "method": athlete.get("hr_zone_method") or "lthr",
        },
    }


@router.put("/zones")
async def update_zones(
    payload: dict,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Update HR zone anchors. method / hr_zone_method: 'lthr' | 'hrr' | 'max_hr' ('max_hr_percent' aliases to 'max_hr')."""
    update = _build_athlete_zones_update(payload)
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields provided")
    try:
        update_res = db.table("athletes").update(update).eq("id", athlete_id).execute()
    except Exception as e:
        print(f"[athlete.zones.put] update failed: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update zones: {str(e)}")
    if getattr(update_res, "data", None) == []:
        raise HTTPException(status_code=403, detail="Zones update was not permitted")
    return {"status": "updated", "fields": list(update.keys())}


@router.patch("/profile")
async def update_athlete_profile(
    payload: AthleteProfileUpdate,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
    user_email: str | None = Depends(get_current_user_email),
):
    """
    Update athlete physiological anchors (e.g., FTP, max HR).
    Should trigger async recalculation of historical TSS if FTP changes.
    """
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    if "threshold_hr" in update_data and update_data.get("threshold_hr") is not None:
        try:
            if int(update_data["threshold_hr"]) > 0:
                update_data["threshold_hr_source"] = "manual"
        except (TypeError, ValueError):
            pass

    # Supabase client JSON-encodes request bodies; normalize non-JSON types.
    for k, v in list(update_data.items()):
        if isinstance(v, (date, datetime)):
            update_data[k] = v.isoformat()

    # Normalize values that can vary by client implementation.
    # - measurement_units: enforce known values
    units = update_data.get("measurement_units")
    if units is not None:
        units_norm = str(units).strip().lower()
        if units_norm in ("metric", "imperial"):
            update_data["measurement_units"] = units_norm
        else:
            raise HTTPException(status_code=422, detail="measurement_units must be 'metric' or 'imperial'")

    # - time_format: enforce known values ("12h" | "24h")
    tf = update_data.get("time_format")
    if tf is not None:
        tf_norm = str(tf).strip().lower()
        # Accept a few common variants from clients (e.g. "12-hour", "12 hour").
        if tf_norm in ("12h", "12-hour", "12 hour", "12hour", "12"):
            update_data["time_format"] = "12h"
        elif tf_norm in ("24h", "24-hour", "24 hour", "24hour", "24"):
            update_data["time_format"] = "24h"
        else:
            raise HTTPException(status_code=422, detail="time_format must be '12h' or '24h'")

    # - gender: used by Banister TRIMP constants; keep supported values narrow
    gender = update_data.get("gender")
    if gender is not None:
        gender_norm = str(gender).strip().lower()
        if gender_norm in ("male", "female"):
            update_data["gender"] = gender_norm
        else:
            raise HTTPException(status_code=422, detail="gender must be 'male' or 'female'")

    # - hr_zone_method: must match CHECK constraint on athletes (alias max_hr_percent -> max_hr)
    if "hr_zone_method" in update_data:
        raw = update_data.get("hr_zone_method")
        if raw is not None:
            try:
                update_data["hr_zone_method"] = optional_canonical_hr_zone_method(raw)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="hr_zone_method must be lthr, hrr, or max_hr",
                )
    # Note: supabase-py/postgrest does not always support chaining `.select()` after `.update()`
    # across versions. We do a follow-up SELECT to return the updated row consistently.
    try:
        update_res = (
            db.table("athletes")
            .update(update_data)
            .eq("id", athlete_id)
            .execute()
        )
    except Exception as e:
        print(f"[athlete.profile.patch] update failed: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update athlete profile: {str(e)}")

    # If RLS blocks the update, some clients won't raise but data may be empty.
    if getattr(update_res, "data", None) == []:
        raise HTTPException(status_code=403, detail="Profile update was not permitted")

    try:
        fresh = db.table("athletes").select("*").eq("id", athlete_id).single().execute()
    except Exception as e:
        print(f"[athlete.profile.patch] fetch after update failed: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Updated profile but failed to re-fetch: {str(e)}")

    if not getattr(fresh, "data", None):
        raise HTTPException(status_code=500, detail="Updated profile but could not load updated record")

    # Sync marketing opt-in/out with Resend whenever privacy_settings.marketing changes.
    new_privacy = update_data.get("privacy_settings") or {}
    if user_email and "marketing" in new_privacy:
        await sync_marketing_contact(user_email, bool(new_privacy["marketing"]))

    return {
        "status": "success",
        "message": "Profile updated successfully",
        "updated_fields": update_data,
        "profile": athlete_dict_with_hr_zones(fresh.data),
    }
@router.delete("")
async def delete_athlete_account(
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
    admin_db = Depends(get_admin_db)
):
    "Permanently delete the athlete account and all associated data."
    # Fetch user_id first to delete from auth
    res = db.table("athletes").select("user_id").eq("id", athlete_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")
    
    user_id = res.data["user_id"]
    
    # Delete athlete (cascades to workouts, biometrics, etc.)
    admin_db.table("athletes").delete().eq("id", athlete_id).execute()
    
    # Delete from Supabase Auth (requires service role key)
    try:
        admin_db.auth.admin.delete_user(user_id)
    except Exception as e:
        print(f"Warning: Failed to delete auth user {user_id}: {str(e)}")
    return {"status": "success", "message": "Account deleted successfully"}
