from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

from app.dependencies import get_admin_db
from app.services import messaging, photon

router = APIRouter(prefix="/v1/messaging", tags=["Messaging"])


class PhotonInbound(BaseModel):
    message_id: str
    sender: str  # E.164 number of the person who texted
    text: str


@router.post("/photon/inbound")
async def photon_inbound(
    payload: PhotonInbound,
    background_tasks: BackgroundTasks,
    x_photon_bridge_token: Optional[str] = Header(default=None),
):
    """
    Called by photon-bridge for each inbound text. Authenticates the bridge with a
    shared token, returns immediately, and runs the coach in the background (the
    reply is texted back through the bridge, not returned here).
    """
    if not photon.verify_bridge_token(x_photon_bridge_token):
        raise HTTPException(status_code=401, detail="Invalid bridge token")
    background_tasks.add_task(
        messaging.handle_inbound_text,
        get_admin_db(),
        payload.sender,
        payload.message_id,
        payload.text,
    )
    return {"status": "accepted"}
