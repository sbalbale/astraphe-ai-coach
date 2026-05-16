from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings

security = HTTPBearer()

def get_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def get_admin_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY)

def _with_auth_token(db: Client, token: str) -> Client:
    """
    Attach the user's JWT so PostgREST queries run with RLS context.
    supabase-py requires explicitly setting the Authorization header for table queries.
    """
    try:
        db.postgrest.auth(token)
    except Exception:
        # Fall back to explicitly setting headers if the underlying client changes.
        try:
            db.postgrest.session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception:
            pass
    return db

async def get_user_db(credentials: HTTPAuthorizationCredentials = Security(security)) -> Client:
    token = credentials.credentials
    return _with_auth_token(get_db(), token)

async def get_current_athlete(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str:
    """Extracts athlete_id from Supabase JWT."""
    token = credentials.credentials
    try:
        user = db.auth.get_user(token)
        user_id = user.user.id
        print(f"Auth DEBUG: user_id={user_id}")
        
        # fetch athletes.id
        athlete_res = db.table("athletes").select("id").eq("user_id", user_id).execute()
        print(f"Auth DEBUG: athlete_res={athlete_res.data}")
        
        if not athlete_res.data:
            raise HTTPException(status_code=404, detail="Athlete profile not found")
        return athlete_res.data[0]["id"]
    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth error: {str(e)}")
        if settings.APP_ENV == "development" and settings.TEST_ATHLETE_ID:
            print(f"WARNING: Falling back to TEST_ATHLETE_ID: {settings.TEST_ATHLETE_ID}")
            # Only safe if the athlete row actually exists in this database.
            try:
                exists = (
                    db.table("athletes")
                    .select("id")
                    .eq("id", settings.TEST_ATHLETE_ID)
                    .maybe_single()
                    .execute()
                )
                if exists and exists.data and exists.data.get("id"):
                    return settings.TEST_ATHLETE_ID
            except Exception:
                pass
            raise HTTPException(
                status_code=401,
                detail="Invalid or stale auth token (local Supabase was likely reset). Please sign out and sign in again.",
            )
        raise HTTPException(status_code=401, detail=f"Invalid or missing token: {str(e)}")


async def get_current_user_tier(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> str:
    """
    Returns the authenticated user's tier (free|trial|premium).
    Source of truth: Supabase Auth app_metadata.tier.
    """
    token = credentials.credentials
    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}
        user_meta = getattr(u, "user_metadata", None) or {}
        tier_raw = (app_meta.get("tier") or user_meta.get("tier") or "free")
        tier = str(tier_raw).strip().lower()
        if tier not in ("free", "trial", "premium"):
            return "free"
        return tier
    except Exception:
        # Tier should never block core flows; treat as free on any auth lookup issues.
        return "free"


async def get_current_gemini_model(
    credentials: HTTPAuthorizationCredentials = Security(security),
    athlete_id: str = Depends(get_current_athlete),
    db: Client = Depends(get_user_db),
) -> str:
    """
    Returns the Gemini/Gemma model name to use for this request.

    Primary: Supabase Auth JWT app_metadata.gemini_model (admin-controlled),
    then user_metadata.gemini_model.
    Fallback: backend .env GEMINI_MODEL, then gemma-4-31b-it.
    """
    fallback = (settings.GEMINI_MODEL or "").strip() or "gemma-4-31b-it"
    token = credentials.credentials

    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}
        user_meta = getattr(u, "user_metadata", None) or {}
        for raw in (app_meta.get("gemini_model"), user_meta.get("gemini_model")):
            if isinstance(raw, str):
                m = raw.strip()
                if m:
                    return m
    except Exception:
        pass

    return fallback


async def get_current_gemini_analysis_model(
    credentials: HTTPAuthorizationCredentials = Security(security),
    athlete_id: str = Depends(get_current_athlete),
    db: Client = Depends(get_user_db),
) -> str:
    """
    Returns the Gemini model name to use for analysis requests (/v1/analysis/*).

    Primary: Supabase Auth JWT app_metadata.gemini_analysis_model (admin-controlled).
    Fallback: backend .env GEMINI_ANALYSIS_MODEL (defaults to a fast, no-reasoning model).
    """
    fallback = (settings.GEMINI_ANALYSIS_MODEL or "").strip() or "gemini-flash-lite-latest"
    token = credentials.credentials

    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}
        raw = app_meta.get("gemini_analysis_model")
        if isinstance(raw, str):
            m = raw.strip()
            if m:
                return m
    except Exception:
        pass

    return fallback