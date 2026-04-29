from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from app.services.ai_coach import get_coach_response, get_coach_response_stream
from app.dependencies import get_current_athlete, get_user_db
import json

class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

@router.post("/message")
async def chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    try:
        coach_reply = get_coach_response(
            athlete_id=athlete_id,
            message=payload.message,
            current_tss=payload.recent_tss,
            db=db,
        )
        return {"status": "success", "reply": coach_reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stream")
async def stream_chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    async def event_generator():
        try:
            async for chunk in get_coach_response_stream(
                athlete_id=athlete_id,
                message=payload.message,
                current_tss=payload.recent_tss,
                db=db,
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")