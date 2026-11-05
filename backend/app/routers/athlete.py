from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import date, datetime, timedelta
from typing import Optional, List
import asyncio
import json

import numpy as np

from app.models.athlete import AthleteState, AthleteProfileUpdate
from app.services.algorithms import compute_z_score
from app.services.hr_zones import athlete_dict_with_hr_zones, get_athlete_zones, optional_canonical_hr_zone_method
from app.services.resend_service import sync_marketing_contact
from app.services.anchor_history import ANCHOR_FIELDS, record_change as record_anchor_change, rescore_and_rebuild
from app.services.background import spawn as spawn_background
from app.dependencies import get_current_athlete, get_current_user_email, get_user_db, get_admin_db, run_supabase_call
from app.core.redis import get_redis
from app.services.time_utils import athlete_local_date, coerce_timezone_offset_min, local_datetime_from_timezone_offset

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
async def onboard_athlete(athlete_id: str = Depends(get_current_athlete)):
    """
    Post-signup hook. It used to seed fake HRV, sleep and a week of sample workouts
    into the new (real) account, which then fed readiness, the coach and the plan as
    if they were the athlete's own data, and duplicated the plan on every call. Real
    data now comes only from the athlete and their connected apps; the endpoint stays
    so existing app versions keep working.
    """
    return {"status": "success", "message": "Athlete onboarded"}



_STATE_CACHE_TTL = 60    # 1 minute — state changes on workout/biometrics saves
_CACHE_TTL = 300         # 5 minutes — profile and zones change rarely


async def _cache_get(key: str) -> dict | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(key: str, data: dict) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.setex(key, _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass


async def _cache_del(key: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass


async def _cache_set_state(key: str, data: dict) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.setex(key, _STATE_CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass


async def _increment_zones_version(athlete_id: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.incr(f"zones_version:{athlete_id}")
    except Exception:
        pass


def _fetch_athlete_name_sync(db, athlete_id: str) -> str | None:
    res = db.table("athletes").select("display_name").eq("id", athlete_id).execute()
    if not res.data:
        return None
    return res.data[0]["display_name"]


def _fetch_latest_tss_sync(db, athlete_id: str) -> dict:
    res = db.table("tss_history").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    return res.data[0] if res.data else {}


def _fetch_latest_bio_sync(db, athlete_id: str) -> dict:
    res = db.table("biometrics").select("*").eq("athlete_id", athlete_id).order("date", desc=True).limit(1).execute()
    return res.data[0] if res.data else {}


def _fetch_latest_weight_kg_sync(db, athlete_id: str) -> float | None:
    res = (
        db.table("biometrics")
        .select("weight_kg")
        .eq("athlete_id", athlete_id)
        .not_.is_("weight_kg", "null")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    raw = res.data[0].get("weight_kg")
    if raw is None:
        return None
    return float(raw)


def _record_manual_weight_sync(db, athlete_id: str, weight_kg: float) -> bool:
    """
    Record a weight the athlete typed in as today's biometrics reading (source "manual").

    The app shows the newest biometrics weight, so without this a stale scale sync would
    keep overriding what the athlete just entered. Nothing is written when the value
    matches the newest reading, so re-saving the profile doesn't create readings.
    Returns True when a reading was written.
    """
    latest = _fetch_latest_weight_kg_sync(db, athlete_id)
    if latest is not None and abs(latest - weight_kg) < 0.05:
        return False

    offset = None
    try:
        res = db.table("athletes").select("timezone_offset_min").eq("id", athlete_id).maybe_single().execute()
        row = getattr(res, "data", None) if res else None
        if isinstance(row, dict):
            offset = row.get("timezone_offset_min")
    except Exception:
        pass
    today = local_datetime_from_timezone_offset(coerce_timezone_offset_min(offset)).date().isoformat()

    metric_sources: dict = {}
    try:
        res = (
            db.table("biometrics")
            .select("metric_sources")
            .eq("athlete_id", athlete_id)
            .eq("date", today)
            .limit(1)
            .execute()
        )
        if res.data and isinstance(res.data[0].get("metric_sources"), dict):
            metric_sources = dict(res.data[0]["metric_sources"])
    except Exception:
        pass
    metric_sources["weight_kg"] = "manual"

    db.table("biometrics").upsert(
        {
            "athlete_id": athlete_id,
            "date": today,
            "weight_kg": round(float(weight_kg), 2),
            "metric_sources": metric_sources,
        },
        on_conflict="athlete_id,date",
    ).execute()
    return True


def _fetch_bio_window_sync(db, athlete_id: str) -> list:
    res = (
        db.table("biometrics")
        .select("date,hrv_rmssd,resting_hr")
        .eq("athlete_id", athlete_id)
        .order("date", desc=True)
        .limit(30)
        .execute()
    )
    return list(reversed(res.data or []))


def _fetch_bio_hist_sync(db, athlete_id: str) -> list:
    res = (
        db.table("biometrics")
        .select("date")
        .eq("athlete_id", athlete_id)
        .order("date", desc=True)
        .limit(70)
        .execute()
    )
    return res.data or []


@router.get("/state", response_model=AthleteState)
async def get_athlete_state(athlete_id: str = Depends(get_current_athlete), db = Depends(get_user_db)):
    """
    Returns the athlete's current physiological state including computed CTL, ATL, TSB, and readiness score.
    """
    cached = await _cache_get(f"state:{athlete_id}")
    if cached is not None:
        return cached

    from app.services.time_utils import athlete_local_date

    display_name, tss_row, bio, window_rows, bio_hist_data, local_today = await asyncio.gather(
        run_supabase_call(lambda: _fetch_athlete_name_sync(db, athlete_id)),
        run_supabase_call(lambda: _fetch_latest_tss_sync(db, athlete_id)),
        run_supabase_call(lambda: _fetch_latest_bio_sync(db, athlete_id)),
        run_supabase_call(lambda: _fetch_bio_window_sync(db, athlete_id)),
        run_supabase_call(lambda: _fetch_bio_hist_sync(db, athlete_id)),
        run_supabase_call(lambda: athlete_local_date(db, athlete_id)),
    )

    if display_name is None:
        raise HTTPException(status_code=404, detail="Athlete not found")

    ctl = tss_row.get("ctl") or 0.0
    atl = tss_row.get("atl") or 0.0
    tsb = tss_row.get("tsb") or 0.0

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

    days_on_platform = _calc_biometrics_streak_days(bio_hist_data)

    state_response = {
        "athlete_id": athlete_id,
        "display_name": display_name,
        "date": local_today,
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
        "readiness_recommendation": "Calculated by Astraphe Intelligence."
    }
    await _cache_set_state(f"state:{athlete_id}", state_response)
    return state_response

@router.get("/metrics")
async def get_athlete_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    metrics: str = Query("ctl,atl,tsb", description="Comma-separated metrics to include"),
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db)
):
    """Returns computed metrics over a date range."""
    if not start_date or not end_date:
        from app.services.time_utils import athlete_local_date

        today = await asyncio.to_thread(athlete_local_date, db, athlete_id)
        start_date = start_date or (today - timedelta(days=42))
        end_date = end_date or today

    tss_res = await asyncio.to_thread(
        db.table("tss_history")
        .select("date,daily_tss,ctl,atl,tsb")
        .eq("athlete_id", athlete_id)
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .order("date")
        .execute
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
    cached = await _cache_get(f"profile:{athlete_id}")
    if cached is not None:
        latest_weight_kg = await asyncio.to_thread(_fetch_latest_weight_kg_sync, db, athlete_id)
        if latest_weight_kg is not None:
            cached["latest_weight_kg"] = latest_weight_kg
        else:
            cached.pop("latest_weight_kg", None)
        return cached

    try:
        res = await asyncio.to_thread(
            db.table("athletes").select("*").eq("id", athlete_id).maybe_single().execute
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load athlete profile")
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")

    result = athlete_dict_with_hr_zones(res.data)
    latest_weight_kg = await asyncio.to_thread(_fetch_latest_weight_kg_sync, db, athlete_id)
    if latest_weight_kg is not None:
        result["latest_weight_kg"] = latest_weight_kg
    await _cache_set(f"profile:{athlete_id}", result)
    return result


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
    cached = await _cache_get(f"zones:{athlete_id}")
    if cached is not None:
        return cached

    res = await asyncio.to_thread(
        db.table("athletes")
        .select("lthr, threshold_hr, max_hr, resting_hr, hr_zone_method")
        .eq("id", athlete_id)
        .maybe_single()
        .execute
    )
    athlete = res.data or {}
    zones = get_athlete_zones(athlete)
    result = {
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
    await _cache_set(f"zones:{athlete_id}", result)
    return result


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
        update_res = await asyncio.to_thread(
            db.table("athletes").update(update).eq("id", athlete_id).execute
        )
    except Exception as e:
        print(f"[athlete.zones.put] update failed: {repr(e)}")
        print(f"[athlete] Failed to update zones: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to update zones")
    if getattr(update_res, "data", None) == []:
        raise HTTPException(status_code=403, detail="Zones update was not permitted")
    await _cache_del(f"zones:{athlete_id}")
    await _cache_del(f"profile:{athlete_id}")
    await _increment_zones_version(athlete_id)
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
    A change to FTP, threshold pace or units is recorded in the anchor history from today and
    re-scores workouts from today on (earlier ones keep the values they were done at).
    """
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    if "max_hr" in update_data:
        # Entered by the athlete: never replaced by the app's estimate (cleared -> estimated again).
        update_data["max_hr_source"] = "manual" if update_data.get("max_hr") else None

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
        update_res = await asyncio.to_thread(
            db.table("athletes")
            .update(update_data)
            .eq("id", athlete_id)
            .execute
        )
    except Exception as e:
        print(f"[athlete.profile.patch] update failed: {repr(e)}")
        print(f"[athlete] Failed to update athlete profile: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to update athlete profile")

    # If RLS blocks the update, some clients won't raise but data may be empty.
    if getattr(update_res, "data", None) == []:
        raise HTTPException(status_code=403, detail="Profile update was not permitted")

    try:
        fresh = await asyncio.to_thread(
            db.table("athletes").select("*").eq("id", athlete_id).single().execute
        )
    except Exception as e:
        print(f"[athlete.profile.patch] fetch after update failed: {repr(e)}")
        print(f"[athlete] Updated profile but failed to re-fetch: {e!r}")
        raise HTTPException(status_code=500, detail="Updated profile but failed to re-fetch")

    if not getattr(fresh, "data", None):
        raise HTTPException(status_code=500, detail="Updated profile but could not load updated record")

    new_weight = update_data.get("weight_kg")
    if isinstance(new_weight, (int, float)) and new_weight > 0:
        try:
            await asyncio.to_thread(_record_manual_weight_sync, db, athlete_id, float(new_weight))
            await _cache_del(f"state:{athlete_id}")
        except Exception as e:
            # The profile is saved; a failed reading only means the old scale value still shows.
            print(f"[athlete.profile.patch] manual weight reading failed: {repr(e)}")

    if any(k in update_data for k in ANCHOR_FIELDS):
        try:
            admin = get_admin_db()
            today = await asyncio.to_thread(athlete_local_date, admin, athlete_id)
            await asyncio.to_thread(record_anchor_change, admin, athlete_id, fresh.data, today)
            spawn_background(asyncio.to_thread(rescore_and_rebuild, admin, athlete_id, today))
        except Exception as e:
            # The profile is saved; history / re-scoring catch up on the next change.
            print(f"[athlete.profile.patch] anchor history update failed: {repr(e)}")

    await _cache_del(f"profile:{athlete_id}")
    await _cache_del(f"zones:{athlete_id}")
    await _increment_zones_version(athlete_id)

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
    """
    Permanently delete the account and all its data.

    Order matters: deleting the auth user cascades to the athlete row and everything
    keyed on it, so it's one step that either happens or doesn't. (Deleting the athlete
    first left an orphaned login that got 404s whenever the auth delete failed.)
    WHOOP and Strava grants are revoked first, best effort.
    """
    from app.services.account_deletion import revoke_provider_grants

    res = await asyncio.to_thread(
        db.table("athletes").select("user_id").eq("id", athlete_id).maybe_single().execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Athlete not found")
    user_id = res.data["user_id"]

    revoked = await revoke_provider_grants(admin_db, athlete_id)
    if revoked:
        print(f"[athlete.delete] provider revocation athlete_id={athlete_id}: {revoked}")

    try:
        await asyncio.to_thread(admin_db.auth.admin.delete_user, user_id)
    except Exception as e:
        print(f"[athlete.delete] auth delete failed user_id={user_id}: {e!r}")
        raise HTTPException(status_code=500, detail="Couldn't delete the account. Please try again.")

    # Normally already gone via ON DELETE CASCADE; make sure.
    try:
        await asyncio.to_thread(admin_db.table("athletes").delete().eq("id", athlete_id).execute)
    except Exception as e:
        print(f"[athlete.delete] athlete row cleanup failed athlete_id={athlete_id}: {e!r}")
    for key in (f"state:{athlete_id}", f"profile:{athlete_id}"):
        await _cache_del(key)
    return {"status": "success", "message": "Account deleted successfully"}
