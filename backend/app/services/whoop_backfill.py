from __future__ import annotations

from datetime import datetime, timedelta, date as date_type
from typing import Any, Optional

from app.services import whoop
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.processing import process_and_save_biometrics, process_and_save_workout, recalculate_tss_history


def _parse_dt(value: str) -> datetime:
    # WHOOP uses RFC3339 with Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pct(part_ms: Optional[float], total_ms: Optional[float]) -> Optional[float]:
    if not part_ms or not total_ms:
        return None
    if total_ms <= 0:
        return None
    return round((part_ms / total_ms) * 100.0, 1)


async def backfill_last_28_days(athlete_id: str, access_token: str, db: Any) -> None:
    """
    Pull last 28 days of WHOOP sleep/recovery/workouts and persist into Supabase.
    This is intended to run right after OAuth connect.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=28)
    start_s = start.isoformat(timespec="milliseconds") + "Z"
    end_s = end.isoformat(timespec="milliseconds") + "Z"

    print(f"[whoop.backfill] start={start_s} end={end_s} athlete_id={athlete_id}")

    # 1) Cycles (Daily Strain)
    cycles = await whoop.fetch_collection(access_token, "cycle", start_s, end_s)
    print(f"[whoop.backfill] cycles={len(cycles)}")

    for cyc in cycles:
        start_time = cyc.get("start")
        if not start_time:
            continue
        d = _parse_dt(start_time).date()
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
        sport_name = (w.get("sport_name") or "other").lower()
        if sport_name in ("weightlifting", "weight lifting", "strength training", "strength_training", "gym", "strength"):
            sport_name = "strength"

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
        process_and_save_workout(payload, athlete_id, db)
    
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
        d: date_type = _parse_dt(created_at).date()
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
        # Standardize to wake date for biological day alignment
        wake_dt = _parse_dt(slp.get("end") or start_time)
        d = wake_dt.date()
        external_id = str(slp.get("id"))

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            external_id=external_id,
            hrv_rmssd=None,
            resting_hr=None,
            sleep_duration_min=sleep_duration_min,
            sleep_score=score.get("sleep_performance_percentage"),
            sleep_deep_pct=_pct(deep, total_sleep_ms),
            sleep_rem_pct=_pct(rem, total_sleep_ms),
            sleep_light_pct=_pct(light, total_sleep_ms),
            sleep_awake_pct=round((awake / (total_sleep_ms + awake)) * 100, 1) if (total_sleep_ms and awake) else 0.0,
            sleep_bedtime=start_time,
            sleep_wakeup=slp.get("end"),
            is_nap=slp.get("nap", False),
            sleep_need_min=None,
            sleep_debt_min=None,
            skin_temp_deviation=None,
            spo2_pct=None,
        )
        process_and_save_biometrics(payload, athlete_id, db)

    print(f"[whoop.backfill] complete athlete_id={athlete_id}")
