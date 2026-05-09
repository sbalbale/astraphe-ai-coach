from __future__ import annotations

from datetime import datetime, timedelta, date as date_type
from typing import Any, Optional

from app.services import whoop
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.processing import process_and_save_biometrics, process_and_save_workout, recalculate_tss_history
from app.dependencies import get_admin_db


def _parse_dt(value: str) -> datetime:
    # WHOOP uses RFC3339 with Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pct(part_ms: Optional[float], total_ms: Optional[float]) -> Optional[float]:
    if not part_ms or not total_ms:
        return None
    if total_ms <= 0:
        return None
    return round((part_ms / total_ms) * 100.0, 1)


async def backfill_historical_data(athlete_id: str, access_token: str, db: Any = None, days: int = 90) -> None:
    """
    Pull historical WHOOP sleep/recovery/workouts and persist into Supabase.
    This is intended to run right after OAuth connect.
    """
    # If no DB provided (common for background tasks), create one.
    if db is None:
        db = get_admin_db()

    # 0) Fetch Profile & Update Athlete (moved from sync.py for speed)
    print(f"[whoop.backfill] Fetching profile for athlete_id={athlete_id}")
    try:
        profile = await whoop.fetch_profile(access_token)
        measurements = await whoop.fetch_body_measurement(access_token)
        
        profile_update = {}
        if profile.get("first_name"): profile_update["display_name"] = profile["first_name"]
        if measurements.get("weight_kilograms"): profile_update["weight_kg"] = measurements["weight_kilograms"]
        if measurements.get("max_heart_rate"): profile_update["max_hr"] = measurements["max_heart_rate"]
        
        # Also update the oauth_token with the external_user_id
        if profile.get("user_id"):
            db.table("oauth_tokens").update({
                "external_user_id": str(profile.get("user_id"))
            }).eq("athlete_id", athlete_id).eq("provider", "whoop").execute()

        if profile_update:
            db.table("athletes").update(profile_update).eq("id", athlete_id).execute()
    except Exception as e:
        print(f"[whoop.backfill] Failed to update profile/measurements: {e}")

    end = datetime.utcnow()
    start = end - timedelta(days=days)
    start_s = start.isoformat(timespec="milliseconds") + "Z"
    end_s = end.isoformat(timespec="milliseconds") + "Z"

    print(f"[whoop.backfill] start={start_s} end={end_s} athlete_id={athlete_id}")

    # Fetch athlete timezone for correct date mapping
    try:
        athlete_res = (
            db.table("athletes")
            .select("timezone_offset_min")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        offset = (athlete_res.data.get("timezone_offset_min") or 0) if (athlete_res and athlete_res.data) else 0
    except Exception:
        offset = 0

    # 1) Cycles (Daily Strain)
    cycles = await whoop.fetch_collection(access_token, "cycle", start_s, end_s)
    print(f"[whoop.backfill] cycles={len(cycles)}")

    for cyc in cycles:
        # WHOOP cycle biological day is best determined by the end of the cycle (the day you wake up)
        # or if end is null (current cycle), use created_at or start + some hours.
        cycle_ref_time = cyc.get("end") or cyc.get("created_at") or cyc.get("start")
        if not cycle_ref_time:
            continue
            
        utc_ref = _parse_dt(cycle_ref_time)
        local_ref = utc_ref + timedelta(minutes=offset)
        d = local_ref.date()
        score = (cyc.get("score") or {}) if isinstance(cyc.get("score"), dict) else {}
        strain = score.get("strain")

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            hrv_rmssd=None,
            resting_hr=None,
            sleep_duration_min=None,
            sleep_score=None,
            sleep_deep_pct=None,
            sleep_rem_pct=None,
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp_deviation=None,
            spo2_pct=None,
        )
        process_and_save_biometrics(payload, athlete_id, db)

    # 2) Workouts First (to establish training load for readiness scores)
    workouts = await whoop.fetch_collection(access_token, "activity/workout", start_s, end_s)
    print(f"[whoop.backfill] workouts={len(workouts)}")

    for w in workouts:
        w_start = w.get("start")
        w_end = w.get("end")
        if not w_start or not w_end:
            continue

        start_dt = _parse_dt(w_start)
        end_dt = _parse_dt(w_end)
        duration_seconds = int(max(0, (end_dt - start_dt).total_seconds()))

        score = (w.get("score") or {}) if isinstance(w.get("score"), dict) else {}
        zone = (score.get("zone_durations") or {}) if isinstance(score.get("zone_durations"), dict) else {}

        total_zone_ms = sum(v for v in zone.values() if isinstance(v, (int, float)))
        z0 = zone.get("zone_zero_milli")
        z1 = zone.get("zone_one_milli")
        z2 = zone.get("zone_two_milli")
        z3 = zone.get("zone_three_milli")
        z4 = zone.get("zone_four_milli")
        z5 = zone.get("zone_five_milli")

        hr0 = int(round(((z0 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr1 = int(round(((z1 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr2 = int(round(((z2 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr3 = int(round(((z3 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr4 = int(round(((z4 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr5 = int(round(((z5 or 0) / total_zone_ms) * 100)) if total_zone_ms else None

        external_id = str(w.get("v1_id") or w.get("id"))
        display_name = (w.get("sport_name") or "Workout")
        sport_name_raw = (w.get("sport_name") or "other")
        sport_name = str(sport_name_raw).strip().lower()
        # Normalize common WHOOP sport names into our internal enums.
        if sport_name in ("weightlifting", "weight lifting", "strength training", "strength_training", "gym", "strength"):
            sport_name = "strength"
        elif sport_name in ("cycling", "bike", "biking", "indoor cycling", "spin", "spinning", "stationary bike", "peloton"):
            # processing.py will normalize cycling -> bike
            sport_name = "cycling"
        elif sport_name in ("running", "run", "treadmill run", "treadmill"):
            sport_name = "run"
        elif sport_name in ("rowing", "row", "rower", "erg", "ergometer"):
            sport_name = "row"
        elif sport_name in (
            "yoga",
            "mobility",
            "stretching",
            "stretch",
            "pilates",
            "barre",
            "tai chi",
            "tai_chi",
            "meditation",
        ):
            sport_name = "mobility"

        payload = WorkoutPayload(
            source="whoop",
            external_id=external_id,
            sport=sport_name,
            title=display_name,
            started_at=start_dt,
            ended_at=end_dt,
            duration_seconds=duration_seconds,
            distance_m=score.get("distance_meter"),
            avg_hr=score.get("average_heart_rate"),
            max_hr=score.get("max_heart_rate"),
            hr_zone_0_pct=hr0,
            hr_zone_1_pct=hr1,
            hr_zone_2_pct=hr2,
            hr_zone_3_pct=hr3,
            hr_zone_4_pct=hr4,
            hr_zone_5_pct=hr5,
        )
        try:
            process_and_save_workout(payload, athlete_id, db)
        except Exception as e:
            # Don't let a single bad record kill the whole backfill.
            print(f"[whoop.backfill] workout_upsert_failed external_id={external_id} sport={sport_name}: {e}")
            continue
    
    # Recalculate TSS history once after all workouts are in
    recalculate_tss_history(athlete_id, db)

    # 2) Recovery (HRV, RHR, spo2, skin temp, recovery score)
    # This will now have access to the training load (ATL/CTL) for readiness scores
    recoveries = await whoop.fetch_collection(access_token, "recovery", start_s, end_s)
    print(f"[whoop.backfill] recoveries={len(recoveries)}")

    for rec in recoveries:
        created_at = rec.get("created_at")
        if not created_at:
            continue
        utc_created = _parse_dt(created_at)
        local_created = utc_created + timedelta(minutes=offset)
        d: date_type = local_created.date()
        score = (rec.get("score") or {}) if isinstance(rec.get("score"), dict) else {}

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            hrv_rmssd=score.get("hrv_rmssd_milli") or score.get("hrv_rmssd_ms"),
            resting_hr=score.get("resting_heart_rate"),
            sleep_duration_min=None,
            sleep_score=None,
            sleep_deep_pct=None,
            sleep_rem_pct=None,
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp_deviation=score.get("skin_temp_celsius"),
            spo2_pct=score.get("spo2_percentage"),
            recovery_score=rec.get("score", {}).get("recovery_score") if isinstance(rec.get("score"), dict) else None,
        )
        process_and_save_biometrics(payload, athlete_id, db)

    # 3) Sleep (duration + stage breakdown + sleep score)
    sleeps = await whoop.fetch_collection(access_token, "activity/sleep", start_s, end_s)
    print(f"[whoop.backfill] sleeps={len(sleeps)}")

    for slp in sleeps:
        start_time = slp.get("start")
        if not start_time:
            continue

        score = (slp.get("score") or {}) if isinstance(slp.get("score"), dict) else {}
        stage = (score.get("stage_summary") or {}) if isinstance(score.get("stage_summary"), dict) else {}
        
        light = stage.get("total_light_sleep_time_milli")
        deep = stage.get("total_slow_wave_sleep_time_milli")
        rem = stage.get("total_rem_sleep_time_milli")
        awake = stage.get("total_awake_time_milli")
        
        # Filter out "empty" sleep records
        total_sleep_ms = sum(v for v in (light, deep, rem) if isinstance(v, (int, float)))
        if not total_sleep_ms or total_sleep_ms <= 0:
            continue

        # Standardize to wake date for biological day alignment, adjusted for athlete timezone
        wake_dt = _parse_dt(slp.get("end") or start_time)
        local_wake = wake_dt + timedelta(minutes=offset)
        d = local_wake.date()
        external_id = str(slp.get("id"))

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            external_id=external_id,
            hrv_rmssd=None,
            resting_hr=None,
            sleep_duration_min=int(total_sleep_ms / 60000),
            sleep_score=score.get("sleep_performance_percentage"),
            sleep_deep_pct=_pct(deep, total_sleep_ms),
            sleep_rem_pct=_pct(rem, total_sleep_ms),
            sleep_light_pct=_pct(light, total_sleep_ms),
            sleep_awake_pct=round((awake / (total_sleep_ms + awake)) * 100, 1) if (total_sleep_ms and awake) else 0.0,
            sleep_bedtime=datetime.fromisoformat(start_time.replace("Z", "+00:00")),
            sleep_wakeup=datetime.fromisoformat((slp.get("end") or start_time).replace("Z", "+00:00")),
            is_nap=slp.get("nap", False),
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp_deviation=None,
            spo2_pct=None,
        )
        process_and_save_biometrics(payload, athlete_id, db)

    print(f"[whoop.backfill] complete athlete_id={athlete_id}")
