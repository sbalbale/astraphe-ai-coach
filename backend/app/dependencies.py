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
            return settings.TEST_ATHLETE_ID
        raise HTTPException(status_code=401, detail=f"Invalid or missing token: {str(e)}")