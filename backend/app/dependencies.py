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
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or missing token")