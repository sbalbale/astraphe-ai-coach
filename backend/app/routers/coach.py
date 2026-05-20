from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from typing import Optional, List
import asyncio
import json
import traceback
from datetime import datetime, timezone

from app.services.ai_coach import (
    build_initialization_message,
    generate_coach_conversation_title,
    get_coach_response,
)
from app.dependencies import (
    get_current_athlete,
    get_user_config,
    get_user_db,
    require_ai_rate_limit,
    UserConfig,
)

class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0
    image_urls: Optional[List[str]] = None

    @field_validator("message")
    @classmethod
    def validate_message_length(cls, v: str) -> str:
        if len(v) > 8000:
            raise ValueError("Message too long (max 8000 characters)")
        return v

class CreateConversation(BaseModel):
    title: Optional[str] = None

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _generate_conversation_title(message: str | None, image_urls: Optional[List[str]] = None) -> str:
    base = (message or "").strip()
    if not base and image_urls:
        return "Images"
    if not base:
        return "New chat"
    base = " ".join(base.replace("\n", " ").split())
    words = base.split(" ")
    title = " ".join(words[:8])
    if len(words) > 8:
        title += "…"
    return title[:60]

def _create_conversation(db, athlete_id: str, title: Optional[str]) -> str:
    res = db.table("coach_conversations").insert({
        "athlete_id": athlete_id,
        "title": title,
        "updated_at": _now_iso(),
    }).execute()
    if not res.data:
        raise RuntimeError("Failed to create conversation")
    return res.data[0]["id"]

def _touch_conversation(db, athlete_id: str, conversation_id: str):
    db.table("coach_conversations").update({"updated_at": _now_iso()}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()

def _maybe_set_conversation_title(db, athlete_id: str, conversation_id: str, title: str):
    try:
        res = (
            db.table("coach_conversations")
            .select("title")
            .eq("id", conversation_id)
            .eq("athlete_id", athlete_id)
            .maybe_single()
            .execute()
        )
        current = (res.data or {}).get("title") if res else None
        if current and str(current).strip():
            return
    except Exception:
        return
    try:
        db.table("coach_conversations").update({"title": title, "updated_at": _now_iso()}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    except Exception:
        return

def _force_set_conversation_title(db, athlete_id: str, conversation_id: str, title: str):
    t = (title or "").strip()[:80]
    if not t:
        return
    try:
        db.table("coach_conversations").update({"title": t, "updated_at": _now_iso()}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    except Exception:
        return

def _insert_message(db, athlete_id: str, conversation_id: str, role: str, content: str, image_urls: Optional[List[str]] = None):
    db.table("coach_messages").insert({
        "athlete_id": athlete_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "image_urls": image_urls or [],
    }).execute()
    if role == "user":
        _maybe_set_conversation_title(db, athlete_id, conversation_id, _generate_conversation_title(content, image_urls=image_urls))
    _touch_conversation(db, athlete_id, conversation_id)

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

def _require_premium(config: UserConfig):
    if config.tier != "premium":
        raise HTTPException(status_code=403, detail="Premium membership required for AI Coach.")


@router.get("/conversations")
async def list_conversations(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    res = (
        db.table("coach_conversations")
        .select("id,title,created_at,updated_at")
        .eq("athlete_id", athlete_id)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
    )
    return {"status": "success", "conversations": res.data or []}

@router.post("/conversations")
async def create_conversation(
    payload: CreateConversation,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    cid = _create_conversation(db, athlete_id, payload.title)
    return {"status": "success", "conversation": {"id": cid, "title": payload.title}}

@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    _ = (
        db.table("coach_conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("athlete_id", athlete_id)
        .maybe_single()
        .execute()
    )
    res = (
        db.table("coach_messages")
        .select("id,role,content,image_urls,created_at")
        .eq("athlete_id", athlete_id)
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .limit(500)
        .execute()
    )
    return {"status": "success", "messages": res.data or []}

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    db.table("coach_conversations").delete().eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    return {"status": "success"}

@router.post("/initialize")
async def initialize_coach(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    """
    Called when the chat UI mounts. Returns a proactive warning if biometrics/load
    anomalies are severe; otherwise a short context-aware greeting.
    """
    _require_premium(config)
    try:
        message, is_proactive = build_initialization_message(athlete_id, db, config.gemini_model)
        return {"status": "success", "message": message, "is_proactive": is_proactive}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/message")
async def chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    _require_premium(config)
    try:
        conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)
        coach_reply, coach_sources = await asyncio.to_thread(
            get_coach_response,
            athlete_id=athlete_id,
            message=payload.message,
            current_tss=payload.recent_tss,
            db=db,
            conversation_id=conversation_id,
            model_name=config.gemini_model,
        )
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)
        try:
            new_title = generate_coach_conversation_title(db, athlete_id, conversation_id, model_name=config.gemini_model)
            _force_set_conversation_title(db, athlete_id, conversation_id, new_title)
        except Exception:
            pass
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "reply": coach_reply,
            "sources": coach_sources,
        }
    except Exception as e:
        print("--- AI COACH CRASH LOG ---")
        traceback.print_exc()
        print("--------------------------")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stream")
async def stream_chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    _require_premium(config)
    async def event_generator():
        conversation_id = payload.conversation_id
        if not conversation_id:
            conversation_id = _create_conversation(db, athlete_id, title=None)
            yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"

        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)

        ai_full = ""
        ai_sources: list = []
        try:
            ai_full, ai_sources = await asyncio.to_thread(
                get_coach_response,
                athlete_id,
                payload.message,
                payload.recent_tss,
                db,
                conversation_id,
                config.gemini_model,
            )
            ai_full = (ai_full or "").strip()
            if not ai_full:
                raise RuntimeError("Model returned an empty response.")

            chunk_size = 600
            for i in range(0, len(ai_full), chunk_size):
                chunk = ai_full[i : i + chunk_size]
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield f"data: {json.dumps({'sources': ai_sources or []})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        else:
            _insert_message(db, athlete_id, conversation_id, role="ai", content=ai_full, image_urls=None)
            try:
                new_title = await asyncio.to_thread(
                    generate_coach_conversation_title,
                    db,
                    athlete_id,
                    conversation_id,
                    config.gemini_model,
                )
                _force_set_conversation_title(db, athlete_id, conversation_id, new_title)
            except Exception:
                pass
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
