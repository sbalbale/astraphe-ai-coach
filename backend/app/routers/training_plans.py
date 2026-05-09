from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_current_athlete, get_user_db


router = APIRouter(prefix="/v1/training-plans", tags=["Training Plans"])

# Canonical values match mobile Workout.sport (see mobile/src/lib/types/training.ts).
_CANONICAL_SPORTS = frozenset(
    {"run", "bike", "swim", "row", "strength", "mobility", "other"}
)
_LEGACY_SPORT = {
    "running": "run",
    "cycling": "bike",
    "swimming": "swim",
    "rowing": "row",
}


def _normalize_plan_sport(raw: object) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "other"
    s = str(raw).strip().lower()
    s = _LEGACY_SPORT.get(s, s)
    if s not in _CANONICAL_SPORTS:
        return "other"
    return s


class SubIntervalPayload(BaseModel):
    name: str = Field(description="'Work', 'Recovery', etc.")
    duration_minutes: int
    target_power_percent_ftp: Optional[int] = None
    target_hr_zone: Optional[int] = None
    description: Optional[str] = None


class IntervalPayload(BaseModel):
    name: str
    duration_minutes: int = Field(..., ge=1, le=600)
    target_power_percent_ftp: Optional[int] = Field(default=None, ge=0, le=300)
    target_hr_zone: Optional[int] = Field(default=None, ge=0, le=8)
    description: Optional[str] = None
    sub_intervals: list[SubIntervalPayload] = Field(default_factory=list)


class WorkoutPayload(BaseModel):
    id: Optional[str] = None
    date: str  # ISO YYYY-MM-DD
    title: str
    sport: str
    primary_zone: str
    duration_minutes: int = Field(..., ge=0, le=600)
    projected_tss: int = Field(..., ge=0, le=2000)
    description: str = ""
    structure: list[IntervalPayload] = Field(default_factory=list)
    completed: bool = False

    @field_validator("sport", mode="before")
    @classmethod
    def coerce_sport(cls, v: object) -> str:
        return _normalize_plan_sport(v)


def _to_workout_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Map `training_plans` DB rows to the strict mobile Workout shape.
    """
    planned_date = row.get("planned_date")
    d = planned_date if isinstance(planned_date, str) else ""

    status = str(row.get("status") or "planned").strip().lower()
    completed = status in ("done", "modified")

    return {
        "id": row.get("id"),
        "date": d,
        "title": row.get("title") or "",
        "sport": _normalize_plan_sport(row.get("sport")),
        "primary_zone": row.get("primary_zone") or "Endurance",
        "duration_minutes": int(row.get("duration_min") or 0),
        "projected_tss": int(row.get("target_tss") or 0),
        "description": row.get("description") or "",
        "structure": row.get("structure") or [],
        "completed": completed,
    }


@router.get("")
async def get_training_plans(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Returns planned workouts (training_plans) as strict Workout objects.
    """
    q = db.table("training_plans").select("*").eq("athlete_id", athlete_id)
    if start_date:
        q = q.gte("planned_date", start_date.isoformat())
    if end_date:
        q = q.lte("planned_date", end_date.isoformat())
    q = q.order("planned_date")

    try:
        res = q.execute()
        rows = res.data or []
        return [_to_workout_row(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch training plans: {str(e)}")


@router.post("")
async def create_training_plan(
    payload: WorkoutPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Create a planned workout (training_plans row).
    """
    try:
        ins = (
            db.table("training_plans")
            .insert(
                {
                    "athlete_id": athlete_id,
                    "planned_date": payload.date,
                    "sport": payload.sport,
                    "title": payload.title,
                    "description": payload.description,
                    "duration_min": payload.duration_minutes,
                    "target_tss": payload.projected_tss,
                    "primary_zone": payload.primary_zone,
                    "structure": [i.model_dump() for i in payload.structure],
                    "status": "done" if payload.completed else "planned",
                    "generated_by": "manual",
                }
            )
            .execute()
        )
        row = (ins.data or [{}])[0]
        return _to_workout_row(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create training plan: {str(e)}")


@router.put("/{training_plan_id}")
async def update_training_plan(
    training_plan_id: str,
    payload: WorkoutPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Update a planned workout (training_plans row).
    """
    try:
        upd = (
            db.table("training_plans")
            .update(
                {
                    "planned_date": payload.date,
                    "sport": payload.sport,
                    "title": payload.title,
                    "description": payload.description,
                    "duration_min": payload.duration_minutes,
                    "target_tss": payload.projected_tss,
                    "primary_zone": payload.primary_zone,
                    "structure": [i.model_dump() for i in payload.structure],
                    "status": "done" if payload.completed else "modified",
                }
            )
            .eq("id", training_plan_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        row = (upd.data or [{}])[0]
        if not row.get("id"):
            raise HTTPException(status_code=404, detail="Training plan not found")
        return _to_workout_row(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update training plan: {str(e)}")


@router.delete("")
async def delete_training_plans(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Delete training plan rows in a date range for the current athlete.
    This is the safe way to \"remove next week's plan\" before re-scheduling.
    """
    if not start_date and not end_date:
        raise HTTPException(status_code=400, detail="start_date or end_date required")

    q = db.table("training_plans").delete().eq("athlete_id", athlete_id)
    if start_date:
        q = q.gte("planned_date", start_date.isoformat())
    if end_date:
        q = q.lte("planned_date", end_date.isoformat())

    try:
        res = q.execute()
        deleted = len(res.data or [])
        return {"status": "success", "deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete training plans: {str(e)}")

