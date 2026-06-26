from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
import logging

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.models.biometrics import DailyBiometrics
from app.models.workout import WorkoutPayload
from app.services.algorithms import compute_strain_score
from app.services.ai_coach import invalidate_context_cache
from app.services import stream_storage
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services.processing import (
    process_and_save_biometrics,
    process_and_save_workout,
    recalculate_tss_history,
    recompute_workout_tss_for_athlete,
)

PROVIDER = "intervals_icu"
AUTH_MODE_BASIC = "basic"
AUTH_MODE_API_KEY_HEADER = "api_key_header"

logger = logging.getLogger(__name__)


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

def _percentage(entry: dict[str, Any], percent_keys: tuple[str, ...], minute_keys: tuple[str, ...], denominator_min: int | None) -> float | None:
    direct = _float(entry, *percent_keys)
    if direct is not None:
        return direct
    minutes = _minutes(entry, *minute_keys)
    if minutes is None or denominator_min is None or denominator_min <= 0:
        return None
    return round((float(minutes) / float(denominator_min)) * 100.0, 1)



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
        _first(entry, "date", "id", "day", "start_date", "startDate", "start_time", "startTime")
    )
    if bio_date is None:
        bio_date = datetime.now(timezone.utc).date()

    sleep_duration_min = _minutes(
        entry,
        "sleep_duration_min",
        "sleepDurationMin",
        "sleep_duration_minutes",
        "sleepSecs",
        "sleep_seconds",
        "sleep",
    )
    sleep_in_bed_min = _minutes(
        entry,
        "sleep_in_bed_min",
        "sleepInBedMin",
        "sleep_in_bed_minutes",
        "time_in_bed_secs",
        "timeInBedSecs",
    )
    sleep_in_bed_or_asleep_min = sleep_in_bed_min or sleep_duration_min

    return DailyBiometrics(
        date=bio_date,
        source=PROVIDER,
        external_id=_source_id(entry) or f"{PROVIDER}:{bio_date.isoformat()}",
        hrv_rmssd=_float(entry, "hrv_rmssd", "hrvRmssd", "hrv"),
        resting_hr=_int(entry, "resting_hr", "restingHR", "resting_heart_rate"),
        weight_kg=_float(entry, "weight_kg", "weightKg", "weight"),
        height_cm=_float(entry, "height_cm", "heightCm", "height"),
        sleep_duration_min=sleep_duration_min,
        sleep_in_bed_min=sleep_in_bed_min,
        sleep_score=_int(entry, "sleep_score", "sleepScore"),
        sleep_deep_pct=_percentage(
            entry,
            ("sleep_deep_pct", "sleepDeepPct", "deep_sleep_pct", "deepSleepPct"),
            ("deepSleepSecs", "sleepDeepSecs", "deep_sleep_secs", "deep_sleep_seconds", "slowWaveSleepSecs"),
            sleep_duration_min,
        ),
        sleep_rem_pct=_percentage(
            entry,
            ("sleep_rem_pct", "sleepRemPct", "rem_sleep_pct", "remSleepPct"),
            ("remSleepSecs", "sleepRemSecs", "rem_sleep_secs", "rem_sleep_seconds"),
            sleep_duration_min,
        ),
        sleep_light_pct=_percentage(
            entry,
            ("sleep_light_pct", "sleepLightPct", "light_sleep_pct", "lightSleepPct"),
            ("lightSleepSecs", "sleepLightSecs", "light_sleep_secs", "light_sleep_seconds"),
            sleep_duration_min,
        ),
        sleep_awake_pct=_percentage(
            entry,
            ("sleep_awake_pct", "sleepAwakePct", "awake_pct", "awakePct"),
            ("awakeSecs", "sleepAwakeSecs", "awake_sleep_secs", "awake_seconds"),
            sleep_in_bed_or_asleep_min,
        ),
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


async def fetch_activity_summaries(
    intervals_athlete_id: str,
    api_key: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    params = {"oldest": start_date.isoformat(), "newest": end_date.isoformat()}
    payload = await _get_json(
        f"/v1/athlete/{intervals_athlete_id}/activities",
        api_key,
        params=params,
        label="activities fetch",
    )
    return _as_list(payload, "activities")


def _coerce_stream_series(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return data
    return None


def _coerce_latlng_series(value: dict[str, Any]) -> list[list[float]] | None:
    lat = value.get("data")
    lng = value.get("data2")
    if not isinstance(lat, list) or not isinstance(lng, list):
        return None
    n = min(len(lat), len(lng))
    points: list[list[float]] = []
    for i in range(n):
        try:
            lat_f = float(lat[i])
            lng_f = float(lng[i])
        except (TypeError, ValueError):
            continue
        if -90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0:
            points.append([lat_f, lng_f])
    return points or None


def _normalize_streams_payload(payload: Any) -> dict[str, list[Any]]:
    if isinstance(payload, list):
        out: dict[str, list[Any]] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            key = item.get("type") or item.get("name")
            if key == "latlng":
                series = _coerce_latlng_series(item) or _coerce_stream_series(item)
            else:
                series = _coerce_stream_series(item)
            if key and series is not None:
                out[str(key)] = series
        return out

    source = payload
    if isinstance(payload, dict):
        for key in ("streams", "time_series", "timeSeries"):
            nested = payload.get(key)
            if isinstance(nested, (dict, list)):
                return _normalize_streams_payload(nested)
    if not isinstance(source, dict):
        return {}

    out: dict[str, list[Any]] = {}
    for key, value in source.items():
        series = _coerce_stream_series(value)
        if series is not None:
            out[str(key)] = series
    return out


async def fetch_activity_streams(activity_id: str, api_key: str) -> dict[str, list[Any]]:
    if not activity_id:
        return {}
    try:
        payload = await _get_json(
            f"/v1/activity/{activity_id}/streams.json",
            api_key,
            label="activity streams fetch",
        )
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_ENTITY):
            logger.info(
                "Intervals.icu activity streams unavailable activity_id=%s status=%s detail=%s",
                activity_id,
                exc.status_code,
                exc.detail,
            )
            return {}
        raise
    return _normalize_streams_payload(payload)


def _upsert_activity_streams(
    db: Any,
    workout_id: str,
    athlete_id: str,
    time_series: dict[str, Any],
) -> bool:
    if not time_series:
        return False
    storage_path, byte_size = stream_storage.upload_time_series_gzip(
        athlete_id, workout_id, time_series
    )
    payload = {
        "workout_id": workout_id,
        "athlete_id": athlete_id,
        "time_series": None,
        "storage_path": storage_path,
        "byte_size": byte_size,
        "content_encoding": stream_storage.CONTENT_ENCODING,
        "resolution_seconds": 1,
    }
    existing = (
        db.table("activity_streams")
        .select("id")
        .eq("workout_id", workout_id)
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        db.table("activity_streams").update(payload).eq("workout_id", workout_id).execute()
    else:
        db.table("activity_streams").insert(payload).execute()
    return True


def _hr_samples_from_streams(streams: dict[str, Any]) -> list[int]:
    hr_stream = streams.get("heartrate")
    if not isinstance(hr_stream, list):
        return []
    samples: list[int] = []
    for value in hr_stream:
        if value is None or isinstance(value, bool):
            continue
        try:
            bpm = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        if 20 <= bpm <= 260:
            samples.append(bpm)
    return samples


def _hr_summary_columns_from_streams(streams: dict[str, Any]) -> dict[str, int]:
    samples = _hr_samples_from_streams(streams)
    if not samples:
        return {}
    return {
        "avg_hr": int(round(sum(samples) / len(samples))),
        "max_hr": max(samples),
    }


def _update_athlete_hr_anchors_from_activity(
    db: Any,
    athlete_id: str,
    activity: dict[str, Any],
) -> dict[str, int | str]:
    update: dict[str, int | str] = {}
    max_hr = _int(activity, "athlete_max_hr", "icu_athlete_max_hr")
    resting_hr = _int(activity, "icu_resting_hr", "resting_hr", "restingHR")
    threshold_hr = _int(activity, "lthr", "threshold_hr", "thresholdHr")
    if max_hr is not None and 80 <= max_hr <= 260:
        update["max_hr"] = max_hr
    if resting_hr is not None and 25 <= resting_hr <= 120:
        update["resting_hr"] = resting_hr
    if threshold_hr is not None and 80 <= threshold_hr <= 230:
        update["threshold_hr"] = threshold_hr
        update["threshold_hr_source"] = "estimated"
    if update:
        db.table("athletes").update(update).eq("id", athlete_id).execute()
    return update


def _hr_zone_columns_from_streams(db: Any, athlete_id: str, streams: dict[str, Any]) -> dict[str, Any]:
    hr_samples = _hr_samples_from_streams(streams)
    if not hr_samples:
        return {}
    athlete_res = (
        db.table("athletes")
        .select("lthr,threshold_hr,max_hr,resting_hr,threshold_hr_source,hr_zone_method")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    athlete = athlete_res.data if athlete_res and athlete_res.data else {}
    zone_dist = compute_zone_distribution(hr_samples, get_athlete_zones(athlete))
    out: dict[str, Any] = _hr_summary_columns_from_streams(streams)
    zone_minutes: dict[int, float] = {}
    duration_min = len(hr_samples) / 60.0
    for idx in range(1, 6):
        pct = zone_dist.get(f"Z{idx}")
        if pct is None:
            continue
        pct_i = int(round(float(pct)))
        out[f"hr_zone_{idx}_pct"] = max(0, min(100, pct_i))
        zone_minutes[idx] = (float(pct) / 100.0) * duration_min
    if zone_minutes:
        out["strain_score"] = compute_strain_score(zone_minutes)
    return out


def _update_workout_hr_zones_from_streams(
    db: Any,
    workout_id: str,
    athlete_id: str,
    streams: dict[str, Any],
) -> bool:
    update = _hr_zone_columns_from_streams(db, athlete_id, streams)
    if not update:
        return False
    db.table("workouts").update(update).eq("id", workout_id).execute()
    return True


async def fetch_workouts(
    intervals_athlete_id: str,
    api_key: str,
    start_date: date,
    end_date: date,
) -> list[WorkoutPayload]:
    activities = await fetch_activity_summaries(intervals_athlete_id, api_key, start_date, end_date)
    workouts: list[WorkoutPayload] = []
    for activity in activities:
        mapped = _map_activity_to_workout_payload(activity)
        if mapped is not None:
            workouts.append(mapped)
    return workouts


async def _save_activity_summary_and_streams(
    activity: dict[str, Any],
    athlete_id: str,
    api_key: str,
    db: Any,
) -> tuple[bool, bool]:
    workout = _map_activity_to_workout_payload(activity)
    if workout is None:
        return False, False
    _update_athlete_hr_anchors_from_activity(db, athlete_id, activity)
    workout_id = await process_and_save_workout(
        workout,
        athlete_id,
        db,
        skip_tss_recalc=True,
        skip_daily_strain_refresh=True,
    )
    activity_id = _source_id(activity)
    streams = await fetch_activity_streams(activity_id, api_key) if activity_id else {}
    streams_saved = _upsert_activity_streams(db, workout_id, athlete_id, streams)
    if streams_saved:
        _update_workout_hr_zones_from_streams(db, workout_id, athlete_id, streams)
    elif activity_id:
        logger.info("Intervals.icu activity streams unavailable activity_id=%s", activity_id)
    return True, streams_saved




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

    activities = await fetch_activity_summaries(intervals_athlete_id, api_key, start_date, end_date)
    workout_count = 0
    stream_count = 0
    for activity in activities:
        saved_workout, saved_streams = await _save_activity_summary_and_streams(
            activity,
            athlete_id,
            api_key,
            db,
        )
        if saved_workout:
            workout_count += 1
        if saved_streams:
            stream_count += 1

    await recompute_workout_tss_for_athlete(athlete_id, db)
    recalculate_tss_history(athlete_id, db)

    biometrics = await fetch_biometrics(intervals_athlete_id, api_key, start_date, end_date)
    biometric_count = 0
    for daily in biometrics:
        process_and_save_biometrics(daily, athlete_id, db, skip_pmc_recalc=True)
        biometric_count += 1

    invalidate_context_cache(athlete_id)
    logger.info(
        "Intervals.icu backfill complete athlete=%s workouts=%s streams=%s biometrics=%s days=%s",
        athlete_id,
        workout_count,
        stream_count,
        biometric_count,
        days,
    )
    return {
        "workouts": workout_count,
        "streams": stream_count,
        "biometrics": biometric_count,
        "days": days,
    }
