import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.perf_log import perf_span, payload_bytes
from app.dependencies import get_current_athlete, get_user_db
from app.core.redis import get_redis
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services import strava as strava_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{settings.API_PREFIX}/activities", tags=["Activity Detail"])

_STREAMS_CACHE_TTL = 86400  # 24 hours (streams are immutable)
_ZONES_CACHE_TTL = 21600    # 6 hours
_DETAIL_CACHE_TTL = 86400


async def _cache_get(key: str) -> dict | list | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(key: str, data: dict | list, ttl: int) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.setex(key, ttl, json.dumps(data, default=str))
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


async def _get_zones_version(athlete_id: str) -> str:
    r = get_redis()
    if r is None:
        return "0"
    try:
        v = await r.get(f"zones_version:{athlete_id}")
        return v.decode() if isinstance(v, bytes) else (v or "0")
    except Exception:
        return "0"


def _hr_from_time_series(time_series: dict | None) -> list:
    if not isinstance(time_series, dict):
        return []
    hr = time_series.get("heartrate")
    return hr if isinstance(hr, list) else []


async def _fetch_stream_row(db, workout_id: str, athlete_id: str) -> dict | None:
    from app.services import stream_storage

    def _load():
        res = (
            db.table("activity_streams")
            .select(
                "time_series, storage_path, byte_size, content_encoding, "
                "resolution_seconds, created_at"
            )
            .eq("workout_id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
        )
        data = getattr(res, "data", None)
        if not data:
            return None
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None
        ts = stream_storage.resolve_time_series(data)
        if ts is None and not data.get("storage_path") and not data.get("time_series"):
            return None
        return {
            "time_series": ts or {},
            "resolution_seconds": data.get("resolution_seconds") or 1,
            "created_at": data.get("created_at"),
        }

    return await asyncio.to_thread(_load)


async def _fetch_laps(db, workout_id: str, athlete_id: str) -> list:
    res = await asyncio.to_thread(
        db.table("activity_laps")
        .select("*")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .order("lap_index")
        .execute
    )
    return res.data or []


async def _fetch_intervals_payload(db, workout_id: str, athlete_id: str) -> dict:
    res = await asyncio.to_thread(
        db.table("workouts")
        .select("intervals, intervals_source, splits_metric, sport")
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Workout not found")
    row = res.data
    return {
        "intervals": row.get("intervals") or [],
        "source": row.get("intervals_source"),
        "splits_metric": row.get("splits_metric") or [],
        "sport": row.get("sport"),
    }


async def _fetch_athlete_zone_defs(db, athlete_id: str) -> tuple[dict, list]:
    athlete_res = await asyncio.to_thread(
        db.table("athletes")
        .select("lthr, threshold_hr, max_hr, resting_hr, hr_zone_method")
        .eq("id", athlete_id)
        .maybe_single()
        .execute
    )
    athlete = athlete_res.data or {}
    zones = get_athlete_zones(athlete)
    return athlete, zones


async def _build_zones_result(
    db,
    workout_id: str,
    athlete_id: str,
    *,
    hr_stream: list | None = None,
    athlete: dict | None = None,
    zones: list | None = None,
) -> dict:
    if athlete is None or zones is None:
        athlete, zones = await _fetch_athlete_zone_defs(db, athlete_id)

    hr_stream = hr_stream if hr_stream is not None else []
    source = "stream"
    distribution = compute_zone_distribution(hr_stream, zones)
    data_points = len(hr_stream)

    if not hr_stream:
        workout_res = await asyncio.to_thread(
            db.table("workouts")
            .select(
                "hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct, duration_seconds"
            )
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute
        )
        workout = workout_res.data if workout_res else None
        if workout:
            summary = {
                f"Z{i}": float(workout.get(f"hr_zone_{i}_pct") or 0)
                for i in range(1, 6)
            }
            if any(summary.values()):
                distribution = summary
                source = "summary"
                data_points = int(workout.get("duration_seconds") or 0)

    return {
        "distribution": distribution,
        "zones": [
            {
                "zone": z.zone,
                "name": z.name,
                "min_bpm": z.min_bpm,
                "max_bpm": z.max_bpm,
            }
            for z in zones
        ],
        "method": athlete.get("hr_zone_method") or "lthr",
        "data_points": data_points,
        "source": source,
    }


@router.get("/{workout_id}/detail")
async def get_activity_detail(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Single round-trip: streams (full time_series), laps, intervals, and zones.
    Zones are computed from the same time_series row (no second DB read).
    """
    detail_cache_key = f"detail:{athlete_id}:{workout_id}"
    version = await _get_zones_version(athlete_id)
    zones_cache_key = f"zones:workout:{athlete_id}:v{version}:{workout_id}"

    cached_detail = await _cache_get(detail_cache_key)
    if cached_detail:
        with perf_span(
            "activity_detail",
            workout_id=workout_id,
            cache="detail_hit",
            bytes=payload_bytes(cached_detail),
        ):
            return cached_detail

    with perf_span("activity_detail", workout_id=workout_id, cache="miss") as span:
        stream_row, laps, intervals = await asyncio.gather(
            _fetch_stream_row(db, workout_id, athlete_id),
            _fetch_laps(db, workout_id, athlete_id),
            _fetch_intervals_payload(db, workout_id, athlete_id),
        )

        streams_payload = stream_row
        hr_stream: list = []
        if stream_row:
            hr_stream = _hr_from_time_series(stream_row.get("time_series"))

        zones_cached = await _cache_get(zones_cache_key)
        if zones_cached:
            zones_payload = zones_cached
        else:
            zones_payload = await _build_zones_result(
                db, workout_id, athlete_id, hr_stream=hr_stream
            )
            await _cache_set(zones_cache_key, zones_payload, _ZONES_CACHE_TTL)

        if stream_row:
            await _cache_set(
                f"streams:{athlete_id}:{workout_id}",
                stream_row,
                _STREAMS_CACHE_TTL,
            )

        result = {
            "streams": streams_payload,
            "laps": laps,
            "intervals": intervals,
            "zones": zones_payload,
        }
        span["bytes"] = payload_bytes(result)
        await _cache_set(detail_cache_key, result, _DETAIL_CACHE_TTL)
        return result


@router.get("/{workout_id}/streams")
async def get_streams(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the raw time-series streams for a workout."""
    cache_key = f"streams:{athlete_id}:{workout_id}"
    cached = await _cache_get(cache_key)
    if cached:
        with perf_span("activity_streams", workout_id=workout_id, cache="hit", bytes=payload_bytes(cached)):
            return cached

    with perf_span("activity_streams", workout_id=workout_id, cache="miss") as span:
        row = await _fetch_stream_row(db, workout_id, athlete_id)
        if not row:
            raise HTTPException(status_code=404, detail="No streams found for this workout")
        span["bytes"] = payload_bytes(row)
        await _cache_set(cache_key, row, _STREAMS_CACHE_TTL)
        return row


@router.get("/{workout_id}/laps")
async def get_laps(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns all laps for a workout, ordered by lap_index."""
    return await _fetch_laps(db, workout_id, athlete_id)


@router.get("/{workout_id}/intervals")
async def get_intervals(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the canonical 500m intervals for a rowing workout."""
    return await _fetch_intervals_payload(db, workout_id, athlete_id)


@router.post("/{workout_id}/hydrate-streams")
async def hydrate_streams(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Fetch and store Strava streams when missing from activity_streams."""
    res = await strava_service.hydrate_workout_streams(db, athlete_id, workout_id)
    version = await _get_zones_version(athlete_id)
    await asyncio.gather(
        _cache_del(f"streams:{athlete_id}:{workout_id}"),
        _cache_del(f"zones:workout:{athlete_id}:v{version}:{workout_id}"),
        _cache_del(f"detail:{athlete_id}:{workout_id}"),
    )
    return res


@router.post("/{workout_id}/refetch-strava")
async def refetch_strava(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Re-ingest this workout from Strava (activity, streams, laps, rowing intervals)."""
    res = await strava_service.refetch_workout_from_strava(db, athlete_id, workout_id, delay=True)
    version = await _get_zones_version(athlete_id)
    await asyncio.gather(
        _cache_del(f"streams:{athlete_id}:{workout_id}"),
        _cache_del(f"zones:workout:{athlete_id}:v{version}:{workout_id}"),
        _cache_del(f"detail:{athlete_id}:{workout_id}"),
    )
    return res


@router.get("/{workout_id}/zones")
async def get_workout_zones(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Computes HR zone distribution for a workout from its stored stream.
    Returns both the distribution and the zone definitions used.
    """
    version = await _get_zones_version(athlete_id)
    cache_key = f"zones:workout:{athlete_id}:v{version}:{workout_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    stream_row = await _fetch_stream_row(db, workout_id, athlete_id)
    hr_stream = _hr_from_time_series(stream_row.get("time_series") if stream_row else None)
    result = await _build_zones_result(db, workout_id, athlete_id, hr_stream=hr_stream)
    await _cache_set(cache_key, result, _ZONES_CACHE_TTL)
    return result
