from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings

security = HTTPBearer()

def get_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def get_admin_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY)

async def get_current_athlete(credentials: HTTPAuthorizationCredentials = Security(security), db: Client = Depends(get_db)) -> str:
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