from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.services.ai_coach import get_coach_response
from app.dependencies import get_current_athlete

class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

@router.post("/message")
async def chat_with_coach(payload: ChatMessage, athlete_id: str = Depends(get_current_athlete)):
    try:
        coach_reply = get_coach_response(athlete_id=athlete_id, message=payload.message, current_tss=payload.recent_tss)
        return {"status": "success", "reply": coach_reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))