from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_current_athlete, get_user_db


router = APIRouter(prefix="/v1/training-plans", tags=["Training Plans"])


Sport = Literal["running", "cycling", "swimming", "rowing", "strength"]


class IntervalPayload(BaseModel):
    name: str
    duration_minutes: int = Field(..., ge=1, le=600)
    target_power_percent_ftp: Optional[int] = Field(default=None, ge=0, le=300)
    target_hr_zone: Optional[int] = Field(default=None, ge=0, le=8)
    description: Optional[str] = None


class WorkoutPayload(BaseModel):
    id: Optional[str] = None
    date: str  # ISO YYYY-MM-DD
    title: str
    sport: Sport
    primary_zone: str
    duration_minutes: int = Field(..., ge=1, le=600)
    projected_tss: int = Field(..., ge=0, le=2000)
    description: str = ""
    structure: list[IntervalPayload] = Field(default_factory=list)
    completed: bool = False


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
        "sport": (row.get("sport") or "cycling"),
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

