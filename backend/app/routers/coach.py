from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
from datetime import datetime

from app.services.ai_coach import (
    build_initialization_message,
    generate_coach_conversation_title,
    get_coach_response,
    get_coach_response_stream,
)
from app.dependencies import get_current_athlete, get_current_gemini_model, get_current_user_tier, get_user_db

class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0
    image_urls: Optional[List[str]] = None

class CreateConversation(BaseModel):
    title: Optional[str] = None

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _generate_conversation_title(message: str | None, image_urls: Optional[List[str]] = None) -> str:
    base = (message or "").strip()
    if not base and image_urls:
        return "Images"
    if not base:
        return "New chat"
    # Compact: 6–8 words, no newlines.
    base = " ".join(base.replace("\n", " ").split())
    words = base.split(" ")
    title = " ".join(words[:8])
    if len(words) > 8:
        title += "…"
    # Avoid super long titles
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
    # RLS will enforce ownership.
    db.table("coach_conversations").update({"updated_at": _now_iso()}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()

def _maybe_set_conversation_title(db, athlete_id: str, conversation_id: str, title: str):
    """
    Sets the title if it's currently null/empty.
    supabase-py doesn't support SQL COALESCE updates cleanly across versions,
    so we do a read then a guarded update.
    """
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
        # If we can't read, don't block chat.
        return

    try:
        db.table("coach_conversations").update({"title": title, "updated_at": _now_iso()}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    except Exception:
        return


def _force_set_conversation_title(db, athlete_id: str, conversation_id: str, title: str):
    """Always overwrite sidebar title (used after each coach reply)."""
    t = (title or "").strip()
    if not t:
        return
    t = t[:80]
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
        _maybe_set_conversation_title(
            db,
            athlete_id,
            conversation_id,
            _generate_conversation_title(content, image_urls=image_urls),
        )
    _touch_conversation(db, athlete_id, conversation_id)

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

def _require_premium(tier: str):
    if tier != "premium":
        raise HTTPException(status_code=403, detail="Premium membership required for AI Coach.")

@router.get("/conversations")
async def list_conversations(
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db = Depends(get_user_db),
):
    _require_premium(tier)
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
    tier: str = Depends(get_current_user_tier),
    db = Depends(get_user_db),
):
    _require_premium(tier)
    cid = _create_conversation(db, athlete_id, payload.title)
    return {"status": "success", "conversation": {"id": cid, "title": payload.title}}

@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    db = Depends(get_user_db),
):
    _require_premium(tier)
    # Ensure conversation exists + is owned by this athlete (RLS will also enforce)
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
    tier: str = Depends(get_current_user_tier),
    db = Depends(get_user_db),
):
    _require_premium(tier)
    # Cascades to messages.
    db.table("coach_conversations").delete().eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    return {"status": "success"}

@router.post("/initialize")
async def initialize_coach(
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db = Depends(get_user_db),
):
    """
    Called when the chat UI mounts. Returns a proactive warning if biometrics/load
    anomalies are severe; otherwise a short context-aware greeting.
    """
    _require_premium(tier)
    try:
        message, is_proactive = build_initialization_message(athlete_id, db, model_name)
        return {"status": "success", "message": message, "is_proactive": is_proactive}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/message")
async def chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db = Depends(get_user_db),
):
    _require_premium(tier)
    try:
        conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)
        coach_reply = get_coach_response(
            athlete_id=athlete_id,
            message=payload.message,
            current_tss=payload.recent_tss,
            db=db,
            conversation_id=conversation_id,
            model_name=model_name,
        )
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)
        try:
            new_title = generate_coach_conversation_title(
                db, athlete_id, conversation_id, model_name=model_name
            )
            _force_set_conversation_title(db, athlete_id, conversation_id, new_title)
        except Exception:
            pass
        return {"status": "success", "conversation_id": conversation_id, "reply": coach_reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stream")
async def stream_chat_with_coach(
    payload: ChatMessage,
    athlete_id: str = Depends(get_current_athlete),
    tier: str = Depends(get_current_user_tier),
    model_name: str = Depends(get_current_gemini_model),
    db = Depends(get_user_db),
):
    _require_premium(tier)
    async def event_generator():
        conversation_id = payload.conversation_id
        if not conversation_id:
            conversation_id = _create_conversation(db, athlete_id, title=None)
            # Send the new conversation id so the client can persist it.
            yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"

        # Persist user message immediately
        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)

        ai_full = ""
        try:
            async for chunk in get_coach_response_stream(
                athlete_id=athlete_id,
                message=payload.message,
                current_tss=payload.recent_tss,
                db=db,
                conversation_id=conversation_id,
                model_name=model_name,
            ):
                ai_full += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        else:
            # Persist assistant message once streaming completes
            if ai_full.strip():
                _insert_message(db, athlete_id, conversation_id, role="ai", content=ai_full, image_urls=None)
                try:
                    new_title = await asyncio.to_thread(
                        generate_coach_conversation_title,
                        db,
                        athlete_id,
                        conversation_id,
                        model_name,
                    )
                    _force_set_conversation_title(db, athlete_id, conversation_id, new_title)
                except Exception:
                    pass
        yield "data: [DONE]\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")