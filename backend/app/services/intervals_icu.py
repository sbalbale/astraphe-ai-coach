from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.ai_coach import invalidate_context_cache
from app.services.processing import (
    process_and_save_biometrics,
    process_and_save_workout,
    recalculate_tss_history,
    recompute_workout_tss_for_athlete,
)

PROVIDER = "intervals_icu"
AUTH_MODE_BASIC = "basic"
AUTH_MODE_API_KEY_HEADER = "api_key_header"


def _api_base() -> str:
    base = (settings.INTERVALS_ICU_API_BASE or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intervals.icu API base URL is not configured",
        )
    return base


def _request_kwargs(api_key: str) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Intervals.icu API key is required")

    mode = (settings.INTERVALS_ICU_AUTH_MODE or AUTH_MODE_BASIC).strip().lower()
    if mode == AUTH_MODE_API_KEY_HEADER:
        return {"headers": {"Authorization": f"ApiKey {key}"}}

    return {"auth": httpx.BasicAuth("API_KEY", key)}


def _intervals_error(response: httpx.Response, label: str) -> HTTPException:
    try:
        body = response.text[:300]
    except Exception:
        body = "<unavailable>"
    return HTTPException(
        status_code=response.status_code,
        detail=f"Intervals.icu {label} failed: {response.status_code} {body}",
    )


async def _get_json(
    path: str,
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    label: str,
) -> Any:
    url = f"{_api_base()}/{path.lstrip('/')}"
    kwargs = _request_kwargs(api_key)
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.get(url, params=params, **kwargs)
    if response.status_code < 200 or response.status_code >= 300:
        raise _intervals_error(response, label)
    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Intervals.icu {label} returned non-JSON",
        ) from exc


def _as_list(payload: Any, *container_keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in container_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _first(entry: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def _float(entry: dict[str, Any], *keys: str) -> float | None:
    value = _first(entry, *keys)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(entry: dict[str, Any], *keys: str) -> int | None:
    value = _float(entry, *keys)
    if value is None:
        return None
    return int(round(value))


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _minutes(entry: dict[str, Any], *keys: str) -> int | None:
    value = _float(entry, *keys)
    if value is None:
        return None
    joined = " ".join(keys).lower()
    if "sec" in joined or joined.endswith("_s"):
        value = value / 60.0
    elif "hour" in joined or ("sleep" in joined and 0 < value <= 24):
        value = value * 60.0
    elif "sleep" in joined and value > 24 * 60:
        value = value / 60.0
    return int(round(value))


def _seconds(entry: dict[str, Any], *keys: str) -> int | None:
    value = _float(entry, *keys)
    if value is None:
        return None
    joined = " ".join(keys).lower()
    if "min" in joined:
        value = value * 60.0
    return int(round(value))


def _source_id(entry: dict[str, Any]) -> str | None:
    raw = _first(entry, "id", "activity_id", "activityId", "file_id", "fileId")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _map_wellness_to_daily_biometrics(entry: dict[str, Any]) -> DailyBiometrics:
    bio_date = _parse_date(
        _first(entry, "date", "day", "start_date", "startDate", "start_time", "startTime")
    )
    if bio_date is None:
        bio_date = datetime.now(timezone.utc).date()

    return DailyBiometrics(
        date=bio_date,
        source=PROVIDER,
        external_id=_source_id(entry) or f"{PROVIDER}:{bio_date.isoformat()}",
        hrv_rmssd=_float(entry, "hrv_rmssd", "hrvRmssd", "hrv"),
        resting_hr=_int(entry, "resting_hr", "restingHR", "resting_heart_rate"),
        weight_kg=_float(entry, "weight_kg", "weightKg", "weight"),
        height_cm=_float(entry, "height_cm", "heightCm", "height"),
        sleep_duration_min=_minutes(
            entry,
            "sleep_duration_min",
            "sleepDurationMin",
            "sleep_duration_minutes",
            "sleepSecs",
            "sleep_seconds",
            "sleep",
        ),
        sleep_in_bed_min=_minutes(
            entry,
            "sleep_in_bed_min",
            "sleepInBedMin",
            "sleep_in_bed_minutes",
            "time_in_bed_secs",
            "timeInBedSecs",
        ),
        sleep_score=_int(entry, "sleep_score", "sleepScore"),
        sleep_deep_pct=_float(entry, "sleep_deep_pct", "sleepDeepPct", "deep_sleep_pct"),
        sleep_rem_pct=_float(entry, "sleep_rem_pct", "sleepRemPct", "rem_sleep_pct"),
        sleep_light_pct=_float(entry, "sleep_light_pct", "sleepLightPct", "light_sleep_pct"),
        sleep_awake_pct=_float(entry, "sleep_awake_pct", "sleepAwakePct", "awake_pct"),
        sleep_bedtime=_parse_datetime(_first(entry, "sleep_bedtime", "sleepBedtime", "bedtime")),
        sleep_wakeup=_parse_datetime(_first(entry, "sleep_wakeup", "sleepWakeup", "wakeup")),
        skin_temp=_float(entry, "skin_temp", "skinTemp", "temperature", "temp"),
        spo2_pct=_float(entry, "spo2_pct", "spo2", "spO2"),
        recovery_score=_int(entry, "recovery_score", "recoveryScore"),
        readiness_score=_int(entry, "readiness_score", "readinessScore", "readiness"),
    )


def _map_activity_to_workout_payload(activity: dict[str, Any]) -> WorkoutPayload | None:
    start_time = _parse_datetime(
        _first(activity, "start_date", "startDate", "start_time", "startTime", "start_date_local")
    )
    if start_time is None:
        return None

    duration_seconds = _seconds(
        activity,
        "duration_seconds",
        "durationSeconds",
        "elapsed_time",
        "elapsedTime",
        "moving_time",
        "movingTime",
        "duration",
    )
    ended_at = _parse_datetime(_first(activity, "end_time", "endTime", "end_date", "endDate"))
    if ended_at is None and duration_seconds:
        ended_at = start_time + timedelta(seconds=duration_seconds)

    return WorkoutPayload(
        source=PROVIDER,
        external_id=_source_id(activity),
        sport=str(_first(activity, "type", "sport", "sport_type", "sportType") or "other"),
        started_at=start_time,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        distance_m=_float(activity, "distance_m", "distanceMeters", "distance"),
        avg_power_w=_int(activity, "avg_power", "avgPower", "average_watts", "averageWatts"),
        norm_power_w=_int(
            activity,
            "norm_power",
            "normPower",
            "normalized_power",
            "weighted_average_watts",
            "weightedAverageWatts",
        ),
        avg_hr=_int(activity, "avg_hr", "avgHr", "average_heartrate", "averageHeartrate"),
        max_hr=_int(activity, "max_hr", "maxHr", "max_heartrate", "maxHeartrate"),
        avg_pace_sec_km=_int(activity, "avg_pace_sec_km", "avgPaceSecKm"),
        tss=_float(activity, "tss", "training_load", "trainingLoad", "icu_training_load"),
        title=str(_first(activity, "name", "title") or "") or None,
    )


async def verify_credentials(intervals_athlete_id: str, api_key: str) -> None:
    today = datetime.now(timezone.utc).date()
    await fetch_biometrics(intervals_athlete_id, api_key, today, today)


async def fetch_biometrics(
    intervals_athlete_id: str,
    api_key: str,
    start_date: date,
    end_date: date,
) -> list[DailyBiometrics]:
    params = {"oldest": start_date.isoformat(), "newest": end_date.isoformat()}
    payload = await _get_json(
        f"/v1/athlete/{intervals_athlete_id}/wellness",
        api_key,
        params=params,
        label="wellness fetch",
    )
    return [_map_wellness_to_daily_biometrics(entry) for entry in _as_list(payload, "wellness")]


async def fetch_workouts(
    intervals_athlete_id: str,
    api_key: str,
    start_date: date,
    end_date: date,
) -> list[WorkoutPayload]:
    params = {"oldest": start_date.isoformat(), "newest": end_date.isoformat()}
    payload = await _get_json(
        f"/v1/athlete/{intervals_athlete_id}/activities",
        api_key,
        params=params,
        label="activities fetch",
    )
    workouts: list[WorkoutPayload] = []
    for activity in _as_list(payload, "activities"):
        mapped = _map_activity_to_workout_payload(activity)
        if mapped is not None:
            workouts.append(mapped)
    return workouts


async def backfill_historical_data(
    athlete_id: str,
    intervals_athlete_id: str,
    api_key: str,
    db: Any,
    days: int = 90,
) -> dict[str, int]:
    days = max(1, min(int(days), 365))
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)

    workouts = await fetch_workouts(intervals_athlete_id, api_key, start_date, end_date)
    workout_count = 0
    for workout in workouts:
        await process_and_save_workout(
            workout,
            athlete_id,
            db,
            skip_tss_recalc=True,
            skip_daily_strain_refresh=True,
        )
        workout_count += 1

    await recompute_workout_tss_for_athlete(athlete_id, db)
    recalculate_tss_history(athlete_id, db)

    biometrics = await fetch_biometrics(intervals_athlete_id, api_key, start_date, end_date)
    biometric_count = 0
    for daily in biometrics:
        process_and_save_biometrics(daily, athlete_id, db, skip_pmc_recalc=True)
        biometric_count += 1

    invalidate_context_cache(athlete_id)
    print(
        f"[intervals_icu.backfill] athlete={athlete_id} workouts={workout_count} "
        f"biometrics={biometric_count} days={days}"
    )
    return {"workouts": workout_count, "biometrics": biometric_count, "days": days}
