import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db
from app.core.redis import get_redis
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services import strava as strava_service

router = APIRouter(prefix=f"{settings.API_PREFIX}/activities", tags=["Activity Detail"])

# Caching helpers
_STREAMS_CACHE_TTL = 86400  # 24 hours (streams are immutable)
_ZONES_CACHE_TTL = 21600    # 6 hours


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
        return v.decode() if v else "0"
    except Exception:
        return "0"


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
        return cached

    res = await asyncio.to_thread(
        db.table("activity_streams")
        .select("time_series, resolution_seconds, created_at")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="No streams found for this workout")
    
    await _cache_set(cache_key, res.data, _STREAMS_CACHE_TTL)
    return res.data


@router.get("/{workout_id}/laps")
async def get_laps(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns all laps for a workout, ordered by lap_index."""
    res = await asyncio.to_thread(
        db.table("activity_laps")
        .select("*")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .order("lap_index")
        .execute
    )
    return res.data or []


@router.get("/{workout_id}/intervals")
async def get_intervals(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the canonical 500m intervals for a rowing workout."""
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
    return {
        "intervals": res.data.get("intervals") or [],
        "source": res.data.get("intervals_source"),
        "splits_metric": res.data.get("splits_metric") or [],
        "sport": res.data.get("sport"),
    }


@router.post("/{workout_id}/hydrate-streams")
async def hydrate_streams(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Fetch and store Strava streams when missing from activity_streams."""
    res = await strava_service.hydrate_workout_streams(db, athlete_id, workout_id)
    # Invalidate caches
    version = await _get_zones_version(athlete_id)
    await asyncio.gather(
        _cache_del(f"streams:{athlete_id}:{workout_id}"),
        _cache_del(f"zones:workout:{athlete_id}:v{version}:{workout_id}"),
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
    # Invalidate caches
    version = await _get_zones_version(athlete_id)
    await asyncio.gather(
        _cache_del(f"streams:{athlete_id}:{workout_id}"),
        _cache_del(f"zones:workout:{athlete_id}:v{version}:{workout_id}"),
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

    athlete_res, stream_res = await asyncio.gather(
        asyncio.to_thread(
            db.table("athletes")
            .select("lthr, threshold_hr, max_hr, resting_hr, hr_zone_method")
            .eq("id", athlete_id)
            .maybe_single()
            .execute
        ),
        asyncio.to_thread(
            db.table("activity_streams")
            .select("time_series")
            .eq("workout_id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute
        )
    )

    athlete = athlete_res.data or {}
    zones = get_athlete_zones(athlete)

    hr_stream = []
    if stream_res and stream_res.data:
        hr_stream = stream_res.data.get("time_series", {}).get("heartrate", [])

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

    result = {
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
    
    await _cache_set(cache_key, result, _ZONES_CACHE_TTL)
    return result
