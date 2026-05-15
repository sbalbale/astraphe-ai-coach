from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db
from app.services.hr_zones import compute_zone_distribution, get_athlete_zones
from app.services import strava as strava_service

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


@router.post("/{workout_id}/hydrate-streams")
async def hydrate_streams(
    workout_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Fetch and store Strava streams when missing from activity_streams."""
    return await strava_service.hydrate_workout_streams(db, athlete_id, workout_id)


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

    source = "stream"
    distribution = compute_zone_distribution(hr_stream, zones)
    data_points = len(hr_stream)

    if not hr_stream:
        workout_res = (
            db.table("workouts")
            .select(
                "hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct, duration_seconds"
            )
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
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
