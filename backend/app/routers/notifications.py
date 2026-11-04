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
def register_token(
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
def unregister_token(
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
    """Settings → "Check it works": a test push to this athlete's devices (one per 30 s)."""
    import time

    from app.services.coach_notifications import claim
    from app.services.push import send_push_to_athlete

    if not claim(athlete_id, "test", str(int(time.time() // 30))):
        raise HTTPException(status_code=429, detail="A test was just sent. Try again in a few seconds.")
    sent = send_push_to_athlete(
        athlete_id=athlete_id,
        title="Test notification",
        body="Notifications are working. Tap to open settings.",
        db=db,
        data={"url": "/profile/notifications", "type": "test"},
    )
    return {"status": "sent" if sent else "no_devices", "delivered_to": sent}


@router.get("/devices")
def list_devices(
    athlete_id: str = Depends(get_current_athlete),
    db=Depends(get_user_db),
):
    """How many devices get push ("Push is on for this iPhone · signed in on 2 devices")."""
    rows = db.table("push_tokens").select("platform,updated_at").eq("athlete_id", athlete_id).execute().data or []
    return {
        "count": len(rows),
        "platforms": sorted({r.get("platform") for r in rows if r.get("platform")}),
    }
