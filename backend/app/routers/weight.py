"""Weight screen: weigh-ins, logging, delete / undo, goal."""

import asyncio
from datetime import date as Date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.cache_invalidation import invalidate_athlete_caches
from app.dependencies import get_current_athlete, get_user_db
from app.services import weight as weight_service
from app.services.time_utils import athlete_local_date

router = APIRouter(prefix="/v1/weight", tags=["Weight"])


class WeighInCreate(BaseModel):
    weight_kg: float = Field(..., ge=20, le=350)
    date: Optional[Date] = None
    body_fat_pct: Optional[float] = Field(None, ge=2, le=75)


class GoalUpdate(BaseModel):
    goal_weight_kg: Optional[float] = Field(None, ge=20, le=350)


@router.get("")
async def get_weight(athlete_id: str = Depends(get_current_athlete), db=Depends(get_user_db)):
    """The last year of weigh-ins (oldest first), goal weight, FTP and preferred units."""
    today = await asyncio.to_thread(athlete_local_date, db, athlete_id)
    return await asyncio.to_thread(weight_service.weight_payload, db, athlete_id, today)


@router.post("")
async def log_weigh_in(
    body: WeighInCreate,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    today = await asyncio.to_thread(athlete_local_date, db, athlete_id)
    if body.date is not None and body.date > today:
        raise HTTPException(status_code=400, detail="Weigh-ins can't be in the future")
    row = await asyncio.to_thread(
        weight_service.log_weigh_in, db, athlete_id, round(body.weight_kg, 2), body.date, body.body_fat_pct
    )
    background_tasks.add_task(invalidate_athlete_caches, athlete_id, profile=True)
    return {"status": "success", "weigh_in": row}


async def _set_deleted(weigh_in_id: str, deleted: bool, athlete_id: str, db, background_tasks: BackgroundTasks):
    row = await asyncio.to_thread(weight_service.set_deleted, db, athlete_id, weigh_in_id, deleted)
    if row is None:
        raise HTTPException(status_code=404, detail="Weigh-in not found")
    background_tasks.add_task(invalidate_athlete_caches, athlete_id, profile=True)
    return {"status": "success", "id": weigh_in_id, "deleted": deleted}


@router.delete("/{weigh_in_id}")
async def delete_weigh_in(
    weigh_in_id: str,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Soft delete: `POST /{id}/restore` undoes it, and a re-sync won't bring it back."""
    return await _set_deleted(weigh_in_id, True, athlete_id, db, background_tasks)


@router.post("/{weigh_in_id}/restore")
async def restore_weigh_in(
    weigh_in_id: str,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    return await _set_deleted(weigh_in_id, False, athlete_id, db, background_tasks)


@router.put("/goal")
async def set_goal(
    body: GoalUpdate,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    goal = round(body.goal_weight_kg, 2) if body.goal_weight_kg is not None else None
    await asyncio.to_thread(weight_service.set_goal, db, athlete_id, goal)
    background_tasks.add_task(invalidate_athlete_caches, athlete_id, profile=True)
    return {"status": "success", "goal_weight_kg": goal}
