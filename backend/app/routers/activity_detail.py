from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones

router = APIRouter(prefix=f"{settings.API_PREFIX}/activities", tags=["Activity Detail"])


@router.get("/{workout_id}/streams")
async def get_streams(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the raw time-series streams for a workout."""
    res = (
        db.table("activity_streams")
        .select("time_series, resolution_seconds, created_at")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="No streams found for this workout")
    return res.data


@router.get("/{workout_id}/laps")
async def get_laps(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns all laps for a workout, ordered by lap_index."""
    res = (
        db.table("activity_laps")
        .select("*")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .order("lap_index")
        .execute()
    )
    return res.data or []


@router.get("/{workout_id}/intervals")
async def get_intervals(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Returns the canonical 500m intervals for a rowing workout."""
    res = (
        db.table("workouts")
        .select("intervals, intervals_source, splits_metric, sport")
        .eq("id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:
        raise HTTPException(status_code=404, detail="Workout not found")
    return {
        "intervals": res.data.get("intervals") or [],
        "source": res.data.get("intervals_source"),
        "splits_metric": res.data.get("splits_metric") or [],
        "sport": res.data.get("sport"),
    }


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
    athlete_res = (
        db.table("athletes")
        .select("lthr, threshold_hr, max_hr, resting_hr, hr_zone_method")
        .eq("id", athlete_id)
        .maybe_single()
        .execute()
    )
    athlete = athlete_res.data or {}
    zones = get_athlete_zones(athlete)

    stream_res = (
        db.table("activity_streams")
        .select("time_series")
        .eq("workout_id", workout_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    hr_stream = []
    if stream_res and stream_res.data:
        hr_stream = stream_res.data.get("time_series", {}).get("heartrate", [])

    distribution = compute_zone_distribution(hr_stream, zones)

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
        "data_points": len(hr_stream),
    }
