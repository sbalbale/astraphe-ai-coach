from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatMessage
from app.services.ai_coach import get_coach_response

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

@router.post("/message")
async def chat_with_coach(payload: ChatMessage):
    """
    Endpoint to send a message to the ASTRAPE AI Coach.
    """
    try:
        # Call the Gemini service
        coach_reply = get_coach_response(
            athlete_id=payload.athlete_id,
            message=payload.message,
            current_tss=payload.recent_tss
        )
        
        return {
            "status": "success",
            "reply": coach_reply
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))