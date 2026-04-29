from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import date, timedelta
from app.dependencies import get_current_athlete, get_current_user_tier, get_user_db

router = APIRouter(prefix="/v1/plan", tags=["Training Plan"])

@router.get("")
async def get_training_plan(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db = Depends(get_user_db)
):
    """Returns the athlete's training plan for a date range."""
    if tier != "premium":
        raise HTTPException(status_code=403, detail="Premium membership required for Training Plan.")
    start_date = start_date or date.today()
    end_date = end_date or (date.today() + timedelta(days=7))
    
    plan_res = db.table("training_plans").select("*").eq("athlete_id", athlete_id).gte("planned_date", start_date.isoformat()).lte("planned_date", end_date.isoformat()).order("planned_date").execute()

    workouts = []
    plan_dict = {}

    for row in plan_res.data:
        d = date.fromisoformat(row["planned_date"])
        day = str(d.day)
        
        workouts.append({
            "type": row["sport"],
            "title": row["title"],
            "date": d.strftime("%a"),
            "duration": f'{row.get("duration_min", 0)}m',
            "load": row.get("target_tss", 0)
        })
        
        plan_dict[day] = {
            "type": row["sport"],
            "title": row["title"],
            "duration": f'{row.get("duration_min", 0)} min',
            "tss": row.get("target_tss", 0),
            "status": row["status"],
            "note": row.get("description", "")
        }

    return {
        "workouts": workouts,
        "plan": plan_dict
    }