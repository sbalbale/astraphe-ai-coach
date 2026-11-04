from __future__ import annotations

import json

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_current_athlete, get_user_db
from app.services import plan_matching


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


class SubIntervalPayload(BaseModel):  # minutes may be decimals (1:30 = 1.5)
    name: str = Field(description="'Work', 'Recovery', etc.")
    duration_minutes: float
    target_power_percent_ftp: Optional[int] = None
    target_hr_zone: Optional[int] = None
    description: Optional[str] = None


class IntervalPayload(BaseModel):
    name: str
    duration_minutes: float = Field(..., gt=0, le=600)
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


def _plain_description(raw: Any) -> str:
    """The coach's notes; '' for the workout JSON older sessions stored here instead."""
    text = str(raw or "")
    if text.lstrip().startswith("{"):
        try:
            if isinstance(json.loads(text), dict):
                return ""
        except ValueError:
            pass
    return text


def _to_workout_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Map `training_plans` DB rows to the strict mobile Workout shape.
    """
    planned_date = row.get("planned_date")
    d = planned_date if isinstance(planned_date, str) else ""

    status = str(row.get("status") or "planned").strip().lower()
    # Only "done" is completed. "modified" just means the session was edited or moved
    # (PUT without completed=True), so it used to show moved future sessions as done.
    completed = status == "done"

    return {
        "id": row.get("id"),
        "date": d,
        "title": row.get("title") or "",
        "sport": _normalize_plan_sport(row.get("sport")),
        "primary_zone": row.get("primary_zone") or "Endurance",
        "duration_minutes": int(row.get("duration_min") or 0),
        "projected_tss": int(row.get("target_tss") or 0),
        "description": _plain_description(row.get("description")),
        "structure": row.get("structure") or [],
        "completed": completed,
        # Link to the recorded workout that completed it (null when done by hand or not done).
        "completed_workout_id": row.get("completed_workout_id"),
        "link_source": row.get("link_source"),
        "linked_workout": None,
    }


def _with_linked_workouts(db, athlete_id: str, rows: list[dict]) -> list[dict]:
    """Attach a short summary of each linked workout (one query for the whole list)."""
    out = [_to_workout_row(r) for r in rows]
    ids = [o["completed_workout_id"] for o in out if o.get("completed_workout_id")]
    if ids:
        try:
            by_id = plan_matching.linked_workouts_by_id(db, athlete_id, ids)
        except Exception as e:  # never fail the plan list over the summaries
            print(f"[training_plans] linked workout lookup failed: {e!r}")
            by_id = {}
        for o in out:
            o["linked_workout"] = by_id.get(o.get("completed_workout_id") or "")
    return out


@router.get("")
def get_training_plans(
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
        return _with_linked_workouts(db, athlete_id, rows)
    except Exception as e:
        print(f"[training_plans] Failed to fetch training plans: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to fetch training plans")


@router.post("")
def create_training_plan(
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
        print(f"[training_plans] Failed to create training plan: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to create training plan")


@router.put("/{training_plan_id}")
def update_training_plan(
    training_plan_id: str,
    payload: WorkoutPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Update a planned workout (training_plans row). Marking it not done also unlinks the
    recorded workout (and keeps auto-match from relinking that one).
    """
    try:
        update: dict[str, Any] = {
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
        if not payload.completed:
            cur = (
                db.table("training_plans")
                .select("completed_workout_id,dismissed_workout_ids")
                .eq("id", training_plan_id)
                .eq("athlete_id", athlete_id)
                .limit(1)
                .execute()
            ).data or []
            wid = cur[0].get("completed_workout_id") if cur else None
            if wid:
                update["completed_workout_id"] = None
                update["link_source"] = None
                update["dismissed_workout_ids"] = list(dict.fromkeys([*(cur[0].get("dismissed_workout_ids") or []), wid]))
        upd = (
            db.table("training_plans")
            .update(update)
            .eq("id", training_plan_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        row = (upd.data or [{}])[0]
        if not row.get("id"):
            raise HTTPException(status_code=404, detail="Training plan not found")
        return _with_linked_workouts(db, athlete_id, [row])[0]
    except HTTPException:
        raise
    except Exception as e:
        print(f"[training_plans] Failed to update training plan: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to update training plan")


@router.delete("/{training_plan_id}")
def delete_training_plan(
    training_plan_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """
    Delete one planned workout (training_plans row) belonging to this athlete.
    """
    try:
        res = (
            db.table("training_plans")
            .delete()
            .eq("id", training_plan_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )
        deleted = len(res.data or [])
        if deleted < 1:
            raise HTTPException(status_code=404, detail="Training plan not found")
        return {"status": "success", "id": training_plan_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[training_plans] Failed to delete training plan: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to delete training plan")


@router.delete("")
def delete_training_plans(
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
        print(f"[training_plans] Failed to delete training plans: {e!r}")
        raise HTTPException(status_code=500, detail="Failed to delete training plans")



# --- Linking recorded workouts ----------------------------------------------------------


class LinkPayload(BaseModel):
    workout_id: str
    # Move the link when this workout already completes another session.
    move: bool = False


class DismissPayload(BaseModel):
    workout_id: str


def _link_error(e: Exception):
    if isinstance(e, plan_matching.LinkConflict):
        raise HTTPException(
            status_code=409,
            detail={"message": "This workout already completes another session.", "linked_to": e.other},
        )
    if isinstance(e, LookupError):
        raise HTTPException(status_code=404, detail=str(e))
    print(f"[training_plans] link failed: {e!r}")
    raise HTTPException(status_code=500, detail="Failed to update the link")


@router.get("/{training_plan_id}/candidates")
def link_candidates(
    training_plan_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Recorded workouts within two days of the session, best fit first, plus the one-tap suggestion."""
    try:
        return plan_matching.candidates_for_plan(db, athlete_id, training_plan_id)
    except Exception as e:
        _link_error(e)


@router.post("/{training_plan_id}/link")
def link_workout(
    training_plan_id: str,
    payload: LinkPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Link a recorded workout by hand (marks the session done). 409 if it completes another session."""
    try:
        row = plan_matching.link(db, athlete_id, training_plan_id, payload.workout_id, source="manual", move=payload.move)
        return _with_linked_workouts(db, athlete_id, [row])[0]
    except Exception as e:
        _link_error(e)


@router.delete("/{training_plan_id}/link")
def unlink_workout(
    training_plan_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Unlink: the session goes back to not done and auto-match won't relink that workout."""
    try:
        row = plan_matching.unlink(db, athlete_id, training_plan_id)
        return _to_workout_row(row)
    except Exception as e:
        _link_error(e)


@router.post("/{training_plan_id}/dismiss")
def dismiss_suggestion(
    training_plan_id: str,
    payload: DismissPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """"Not this one": stop suggesting (and auto-matching) this workout for the session."""
    try:
        row = plan_matching.dismiss(db, athlete_id, training_plan_id, payload.workout_id)
        return _to_workout_row(row)
    except Exception as e:
        _link_error(e)
