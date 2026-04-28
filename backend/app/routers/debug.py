from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.config import settings
from app.dependencies import get_current_athlete, get_user_db

router = APIRouter(prefix="/v1/debug", tags=["Debug"])


@router.get("/connection")
async def debug_connection(
    athlete_id: str = Depends(get_current_athlete),
    db: Client = Depends(get_user_db),
):
    """
    End-to-end connectivity + RLS verification for the currently logged-in user.
    Only available in development to avoid leaking environment details.
    """
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=404, detail="Not found")

    athletes = db.table("athletes").select("id,user_id,display_name,created_at").eq("id", athlete_id).execute().data
    workouts_count = (
        db.table("workouts")
        .select("id", count="exact")
        .eq("athlete_id", athlete_id)
        .limit(1)
        .execute()
        .count
        or 0
    )
    biometrics_count = (
        db.table("biometrics")
        .select("id", count="exact")
        .eq("athlete_id", athlete_id)
        .limit(1)
        .execute()
        .count
        or 0
    )
    plan_count = (
        db.table("training_plans")
        .select("id", count="exact")
        .eq("athlete_id", athlete_id)
        .limit(1)
        .execute()
        .count
        or 0
    )

    athlete_row = athletes[0] if athletes else None

    return {
        "backend_env": settings.APP_ENV,
        "backend_supabase_url": settings.SUPABASE_URL,
        "athlete": athlete_row,
        "counts_visible_under_rls": {
            "workouts": workouts_count,
            "biometrics": biometrics_count,
            "training_plans": plan_count,
        },
        "notes": [
            "If athlete is null -> your auth user exists but no athletes row is visible under RLS for this JWT.",
            "If counts are 0 but you expect data -> you are likely logged into a different Supabase project/environment.",
        ],
    }

