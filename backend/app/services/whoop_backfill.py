from __future__ import annotations

from datetime import datetime, timedelta, date as date_type
from typing import Any, Optional

from app.services import whoop
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.processing import process_and_save_biometrics, process_and_save_workout


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

    # 1) Recovery (HRV, RHR, spo2, skin temp, recovery score)
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
            day_strain=None,
            skin_temp_deviation=score.get("skin_temp_celsius"),
            spo2_pct=score.get("spo2_percentage"),
        )
        process_and_save_biometrics(payload, athlete_id, db)

    # 2) Sleep (duration + stage breakdown + sleep score)
    sleeps = await whoop.fetch_collection(access_token, "activity/sleep", start_s, end_s)
    print(f"[whoop.backfill] sleeps={len(sleeps)}")

    for slp in sleeps:
        start_time = slp.get("start")
        if not start_time:
            continue
        d = _parse_dt(start_time).date()

        score = (slp.get("score") or {}) if isinstance(slp.get("score"), dict) else {}
        stage = (score.get("stage_summary") or {}) if isinstance(score.get("stage_summary"), dict) else {}

        light = stage.get("total_light_sleep_time_milli")
        deep = stage.get("total_slow_wave_sleep_time_milli")
        rem = stage.get("total_rem_sleep_time_milli")
        total_sleep_ms = sum(v for v in (light, deep, rem) if isinstance(v, (int, float)))
        sleep_duration_min = int(total_sleep_ms / 60000) if total_sleep_ms else None

        payload = DailyBiometrics(
            date=d,
            source="whoop",
            hrv_rmssd=None,
            resting_hr=None,
            sleep_duration_min=sleep_duration_min,
            sleep_score=score.get("sleep_performance_percentage"),
            sleep_deep_pct=_pct(deep, total_sleep_ms),
            sleep_rem_pct=_pct(rem, total_sleep_ms),
            sleep_need_min=None,
            sleep_debt_min=None,
            day_strain=None,
            skin_temp_deviation=None,
            spo2_pct=None,
        )
        process_and_save_biometrics(payload, athlete_id, db)

    # 3) Workouts
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

        # Map WHOOP zones into pct of total recorded time.
        hr0 = int(round(((z0 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr1 = int(round(((z1 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr2 = int(round(((z2 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr3 = int(round(((z3 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr4 = int(round(((z4 or 0) / total_zone_ms) * 100)) if total_zone_ms else None
        hr5 = int(round(((z5 or 0) / total_zone_ms) * 100)) if total_zone_ms else None

        external_id = str(w.get("v1_id") or w.get("id"))
        # Persist a display name while normalizing sport to our internal enum.
        display_name = (w.get("sport_name") or "Workout")  # e.g. "Weightlifting"
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

    print(f"[whoop.backfill] complete athlete_id={athlete_id}")

