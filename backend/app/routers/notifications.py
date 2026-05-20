from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal

from app.dependencies import get_current_athlete, get_user_db
from app.config import settings

router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])

VALID_PLATFORMS = {"ios", "android", "web"}


class TokenPayload(BaseModel):
    token: str
    platform: Literal["ios", "android", "web"]


@router.post("/token")
async def register_token(
    payload: TokenPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Register or refresh a push token for the current athlete's device."""
    if not payload.token or len(payload.token) > 8192:
        raise HTTPException(status_code=422, detail="Invalid token")

    db.table("push_tokens").upsert(
        {
            "athlete_id": athlete_id,
            "token": payload.token,
            "platform": payload.platform,
            "updated_at": "now()",
        },
        on_conflict="athlete_id,token",
    ).execute()

    return {"status": "registered", "platform": payload.platform}


@router.delete("/token")
async def unregister_token(
    payload: TokenPayload,
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Remove a push token (e.g. on sign-out or permission revocation)."""
    db.table("push_tokens").delete().eq("athlete_id", athlete_id).eq(
        "token", payload.token
    ).execute()
    return {"status": "removed"}


@router.post("/test")
async def send_test_notification(
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """Send a test push to all registered tokens. Development only."""
    if settings.APP_ENV == "production":
        raise HTTPException(status_code=403, detail="Test endpoint disabled in production")

    from app.services.push import send_push_to_athlete

    sent = send_push_to_athlete(
        athlete_id=athlete_id,
        title="ASTRAPE",
        body="Push notifications are working!",
        db=db,
        data={"url": "/dashboard"},
    )
    return {"status": "sent", "delivered_to": sent}
