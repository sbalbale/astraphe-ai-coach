from fastapi import APIRouter, HTTPException, Depends, UploadFile, BackgroundTasks
from fastapi.responses import StreamingResponse
from pathlib import Path
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
    _load_conversation_history,
    _strip_internal_reasoning,
)
from app.services.memory import extract_and_save_memories
from app.dependencies import (
    get_current_athlete,
    get_user_config,
    get_user_db,
    require_ai_rate_limit,
    UserConfig,
)

_ALLOWED_DOC_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls"}
_MAX_DOC_BYTES = 10 * 1024 * 1024  # 10 MB


async def _run_memory_extraction(
    athlete_id: str,
    conversation_excerpt: list[dict],
    db,
    model_name: str | None,
) -> None:
    await asyncio.to_thread(extract_and_save_memories, athlete_id, conversation_excerpt, db, model_name)


class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0
    image_urls: Optional[List[str]] = None
    document_contents: Optional[List[str]] = None

    @field_validator("message")
    @classmethod
    def validate_message_length(cls, v: str) -> str:
        if len(v) > 8000:
            raise ValueError("Message too long (max 8000 characters)")
        return v

    @field_validator("document_contents")
    @classmethod
    def validate_document_contents(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > 3:
            raise ValueError("Max 3 documents per message")
        return [c[:10000] for c in v]

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
    messages = res.data or []
    for m in messages:
        if m.get("role") == "ai":
            m["content"] = _strip_internal_reasoning(str(m.get("content") or ""))
    return {"status": "success", "messages": messages}

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

@router.post("/upload-document")
async def upload_document(
    file: UploadFile,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    """
    Parse an uploaded PDF, CSV, or Excel file and return the extracted text.
    The frontend should include this text in the next message's document_contents field.
    """
    _require_premium(config)
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_DOC_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(_ALLOWED_DOC_EXTENSIONS)}")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_DOC_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        from app.services.file_parser import parse_document
        text = await asyncio.to_thread(parse_document, file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse document: {e}")

    if not (text or "").strip():
        raise HTTPException(status_code=422, detail="No text content could be extracted from this document.")

    return {
        "status": "success",
        "filename": filename,
        "chars": len(text),
        "content": text,
    }


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
    Also returns the athlete's top contextual memories for frontend suggestions.
    """
    _require_premium(config)
    try:
        from app.services.memory import retrieve_relevant_memories
        from app.services.ai_coach import build_initialization_message
        
        # Parallelize the slow Gemini-based tasks
        msg_task = asyncio.to_thread(build_initialization_message, athlete_id, db, config.gemini_model)
        mem_task = asyncio.to_thread(retrieve_relevant_memories, athlete_id, "upcoming races, goals, trips, and injuries", db, top_k=5)
        
        [msg_res, memories] = await asyncio.gather(msg_task, mem_task)
        
        message, is_proactive = msg_res
        memory_strings = [m.get("content") for m in memories if m.get("content")]

        return {
            "status": "success", 
            "message": message, 
            "is_proactive": is_proactive,
            "memories": memory_strings
        }
    except Exception as e:
        # Log error but don't 500 if initialization fails; allow the chat to load with fallbacks
        print(f"[coach.initialize] Failed: {e}")
        return {
            "status": "partial_success",
            "message": None,
            "is_proactive": False,
            "memories": []
        }


@router.post("/message")
async def chat_with_coach(
    payload: ChatMessage,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    _require_premium(config)
    try:
        conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)

        # Prepend any uploaded document content to the effective message for the AI.
        effective_message = payload.message
        if payload.document_contents:
            doc_parts = [
                f"[ATTACHED DOCUMENT {i}]\n{content}"
                for i, content in enumerate(payload.document_contents, 1)
            ]
            effective_message = "\n\n".join(doc_parts) + "\n\n[ATHLETE MESSAGE]\n" + payload.message

        coach_reply, coach_sources = await asyncio.to_thread(
            get_coach_response,
            athlete_id=athlete_id,
            message=effective_message,
            current_tss=payload.recent_tss,
            db=db,
            conversation_id=conversation_id,
            model_name=config.gemini_model,
        )
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)

        # Extract and persist long-term memories from this exchange (background, non-blocking).
        recent_history = _load_conversation_history(db, athlete_id, conversation_id, limit=10)
        background_tasks.add_task(
            _run_memory_extraction,
            athlete_id,
            recent_history,
            db,
            config.gemini_analysis_model,
        )

        try:
            new_title = generate_coach_conversation_title(db, athlete_id, conversation_id, model_name=config.gemini_model)
            _force_set_conversation_title(db, athlete_id, conversation_id, new_title)
        except Exception:
            pass
        try:
            from app.services.push import send_push_to_athlete
            from app.services.text_format import notification_preview

            preview = notification_preview(coach_reply or "")
            send_push_to_athlete(
                athlete_id=athlete_id,
                title="ASTRAPE Coach",
                body=preview,
                db=db,
                data={"url": "/chat"},
                notification_type="coach",
            )
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
    background_tasks: BackgroundTasks,
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

        effective_message = payload.message
        if payload.document_contents:
            doc_parts = [
                f"[ATTACHED DOCUMENT {i}]\n{content}"
                for i, content in enumerate(payload.document_contents, 1)
            ]
            effective_message = "\n\n".join(doc_parts) + "\n\n[ATHLETE MESSAGE]\n" + payload.message

        ai_full = ""
        ai_sources: list = []
        try:
            ai_full, ai_sources = await asyncio.to_thread(
                get_coach_response,
                athlete_id,
                effective_message,
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
            recent_history = _load_conversation_history(db, athlete_id, conversation_id, limit=10)
            background_tasks.add_task(
                _run_memory_extraction,
                athlete_id,
                recent_history,
                db,
                config.gemini_analysis_model,
            )
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
