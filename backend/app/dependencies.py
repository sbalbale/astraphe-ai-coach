from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings

security = HTTPBearer()

def get_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

async def get_current_athlete(credentials: HTTPAuthorizationCredentials = Security(security), db: Client = Depends(get_db)) -> str:
    """Extracts athlete_id from Supabase JWT."""
    token = credentials.credentials
    try:
        user = db.auth.get_user(token)
        user_id = user.user.id
        # fetch athletes.id
        athlete_res = db.table("athletes").select("id").eq("user_id", user_id).execute()
        if not athlete_res.data:
            raise HTTPException(status_code=404, detail="Athlete profile not found")
        return athlete_res.data[0]["id"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid or missing token: {str(e)}")