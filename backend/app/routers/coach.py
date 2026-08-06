from fastapi import APIRouter, HTTPException, Depends, UploadFile, BackgroundTasks, Request
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
from app.services.gemini_quota import GeminiQuotaExceededError
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
_stream_bg_tasks: set[asyncio.Task] = set()


async def _run_memory_extraction(
    athlete_id: str,
    conversation_excerpt: list[dict],
    db,
    model_name: str | None,
) -> None:
    await asyncio.to_thread(extract_and_save_memories, athlete_id, conversation_excerpt, db, model_name)


async def _run_conversation_title(
    db,
    athlete_id: str,
    conversation_id: str,
    model_name: str | None,
) -> None:
    try:
        new_title = await asyncio.to_thread(
            generate_coach_conversation_title,
            db,
            athlete_id,
            conversation_id,
            model_name,
        )
        await asyncio.to_thread(_force_set_conversation_title, db, athlete_id, conversation_id, new_title)
    except Exception:
        pass


class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0
    image_urls: Optional[List[str]] = None
    document_contents: Optional[List[str]] = None
    timezone_offset_min: Optional[int] = None

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

    @field_validator("timezone_offset_min")
    @classmethod
    def validate_timezone_offset_min(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        return max(-14 * 60, min(14 * 60, int(v)))


class InitializeCoachRequest(BaseModel):
    timezone_offset_min: Optional[int] = None

    @field_validator("timezone_offset_min")
    @classmethod
    def validate_timezone_offset_min(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        return max(-14 * 60, min(14 * 60, int(v)))

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


@router.get("/memories")
async def list_memories(
    memory_type: str | None = None,
    limit: int = 50,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    from app.services.memory import list_coach_memories

    rows = await asyncio.to_thread(
        list_coach_memories,
        athlete_id,
        db=db,
        memory_type=memory_type,
        limit=limit,
    )
    return {"status": "success", "memories": rows}


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    payload: dict,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    update: dict = {}
    for k in ("content", "memory_type", "entity_key", "event_date"):
        if k in payload:
            update[k] = payload.get(k)
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    update["updated_at"] = _now_iso()
    res = await asyncio.to_thread(
        db.table("coach_memories")
        .update(update)
        .eq("id", memory_id)
        .eq("athlete_id", athlete_id)
        .execute
    )
    return {"status": "success", "memory": (res.data or [{}])[0] if res else None}


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    res = await asyncio.to_thread(
        db.table("coach_memories")
        .delete()
        .eq("id", memory_id)
        .eq("athlete_id", athlete_id)
        .execute
    )
    return {"status": "success", "deleted": len(res.data or []) if res else 0}

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
    payload: InitializeCoachRequest | None = None,
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
        msg_task = asyncio.to_thread(
            build_initialization_message,
            athlete_id,
            db,
            config.gemini_model,
            None if payload is None else payload.timezone_offset_min,
        )
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


async def _run_coach_response_and_notify(
    athlete_id: str,
    effective_message: str,
    recent_tss: float,
    db,
    conversation_id: str,
    model_name: str | None,
    analysis_model_name: str | None,
    timezone_offset_min: Optional[int],
) -> None:
    """
    The async counterpart of chat_with_coach()'s body, minus the parts that
    have to happen before the HTTP response goes out (creating the
    conversation, inserting the user's message). Runs as a BackgroundTask —
    the client already has its response and may not be connected anymore —
    so every step below is best-effort: a failure here must still leave the
    athlete with *something* in coach_messages and, if possible, a push
    notification, rather than a silently stuck "thinking" placeholder.
    """
    try:
        coach_reply, coach_sources = await asyncio.to_thread(
            get_coach_response,
            athlete_id=athlete_id,
            message=effective_message,
            current_tss=recent_tss,
            db=db,
            conversation_id=conversation_id,
            model_name=model_name,
            timezone_offset_min=timezone_offset_min,
        )
    except GeminiQuotaExceededError as e:
        # Both the primary and fallback chat models' free-tier RPM budgets
        # were exhausted (gemini_quota.wait_for_slot already waited as long
        # as it reasonably could before giving up) — tell the athlete
        # something actionable instead of the generic error below.
        retry_min = max(1, round(e.retry_after_sec / 60))
        coach_reply = (
            f"I've hit the AI model's request limit for the moment — try again in "
            f"about {retry_min} minute{'s' if retry_min != 1 else ''}."
        )
        coach_sources = []
    except Exception:
        traceback.print_exc()
        coach_reply = "Sorry, I ran into an error putting that response together. Please try asking again."
        coach_sources = []

    try:
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)
    except Exception:
        traceback.print_exc()
        return  # Nothing to notify/extract from if the reply itself never landed.

    try:
        recent_history = await asyncio.to_thread(
            _load_conversation_history, db, athlete_id, conversation_id, 10
        )
        await _run_memory_extraction(athlete_id, recent_history, db, analysis_model_name)
    except Exception:
        pass

    await _run_conversation_title(db, athlete_id, conversation_id, model_name)

    try:
        from app.services.push import send_push_to_athlete
        from app.services.text_format import notification_preview

        preview = notification_preview(coach_reply or "")
        send_push_to_athlete(
            athlete_id=athlete_id,
            title="ASTRAPHE Coach",
            body=preview,
            db=db,
            data={"url": "/chat", "conversation_id": conversation_id},
            notification_type="coach",
        )
    except Exception:
        pass


@router.post("/message/async")
async def submit_coach_message(
    payload: ChatMessage,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    """
    Fire-and-forget counterpart to /message and /stream: inserts the user's
    message and returns immediately with `status: "pending"` rather than
    holding the connection open for the full (sometimes multi-hop) Gemini
    call. The reply lands in coach_messages and triggers the existing push
    notification (see _run_coach_response_and_notify) whenever it's ready —
    the client is expected to poll GET /conversations/{id}/messages (or just
    wait for the push) rather than block on this request.
    """
    _require_premium(config)
    conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
    _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls)

    effective_message = payload.message
    if payload.document_contents:
        doc_parts = [
            f"[ATTACHED DOCUMENT {i}]\n{content}"
            for i, content in enumerate(payload.document_contents, 1)
        ]
        effective_message = "\n\n".join(doc_parts) + "\n\n[ATHLETE MESSAGE]\n" + payload.message

    background_tasks.add_task(
        _run_coach_response_and_notify,
        athlete_id,
        effective_message,
        payload.recent_tss,
        db,
        conversation_id,
        config.gemini_model,
        config.gemini_analysis_model,
        payload.timezone_offset_min,
    )

    return {
        "status": "pending",
        "conversation_id": conversation_id,
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
            timezone_offset_min=payload.timezone_offset_min,
        )
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)

        # Extract and persist long-term memories from this exchange (background, non-blocking).
        recent_history = await asyncio.to_thread(
                    _load_conversation_history, db, athlete_id, conversation_id, 10
                )
        background_tasks.add_task(
            _run_memory_extraction,
            athlete_id,
            recent_history,
            db,
            config.gemini_analysis_model,
        )

        background_tasks.add_task(
            _run_conversation_title,
            db,
            athlete_id,
            conversation_id,
            config.gemini_model,
        )
        try:
            from app.services.push import send_push_to_athlete
            from app.services.text_format import notification_preview

            preview = notification_preview(coach_reply or "")
            send_push_to_athlete(
                athlete_id=athlete_id,
                title="ASTRAPHE Coach",
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
    except GeminiQuotaExceededError as e:
        retry_min = max(1, round(e.retry_after_sec / 60))
        raise HTTPException(
            status_code=429,
            detail=f"AI model request limit reached — try again in about {retry_min} minute{'s' if retry_min != 1 else ''}.",
        )
    except Exception as e:
        print("--- AI COACH CRASH LOG ---")
        traceback.print_exc()
        print("--------------------------")
        raise HTTPException(status_code=500, detail=str(e))


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_COACH_STREAM_KEEPALIVE_SEC = 15.0


async def _stream_coach_agentic(
    *,
    athlete_id: str,
    effective_message: str,
    recent_tss: float,
    db,
    conversation_id: str,
    model_name: str | None,
    timezone_offset_min: int | None,
):
    """Run agentic coach in a worker thread; yield progress dicts and final result."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("progress", event))

    def run() -> None:
        try:
            result = get_coach_response(
                athlete_id,
                effective_message,
                recent_tss,
                db,
                conversation_id,
                model_name,
                timezone_offset_min,
                progress_callback=progress,
            )
            loop.call_soon_threadsafe(queue.put_nowait, ("done", result))
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))

    worker = asyncio.create_task(asyncio.to_thread(run))
    try:
        while True:
            try:
                kind, payload = await asyncio.wait_for(
                    queue.get(), timeout=_COACH_STREAM_KEEPALIVE_SEC
                )
            except asyncio.TimeoutError:
                yield {"_keepalive": True}
                continue
            if kind == "progress":
                yield payload
            elif kind == "done":
                yield {"_result": payload}
                return
            elif kind == "error":
                raise payload
    finally:
        if not worker.done():
            await worker


@router.post("/stream")
async def stream_chat_with_coach(
    payload: ChatMessage,
    background_tasks: BackgroundTasks,
    request: Request,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    _require_premium(config)

    async def event_generator():
        conversation_id = payload.conversation_id
        if not conversation_id:
            conversation_id = await asyncio.to_thread(_create_conversation, db, athlete_id, None)

        yield f"data: {json.dumps({'conversation_id': conversation_id, 'status': 'started'})}\n\n"

        await asyncio.to_thread(
            _insert_message,
            db,
            athlete_id,
            conversation_id,
            "user",
            payload.message,
            payload.image_urls,
        )

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
            async for event in _stream_coach_agentic(
                athlete_id=athlete_id,
                effective_message=effective_message,
                recent_tss=payload.recent_tss,
                db=db,
                conversation_id=conversation_id,
                model_name=config.gemini_model,
                timezone_offset_min=payload.timezone_offset_min,
            ):
                if event.get("_keepalive"):
                    yield ": ping\n\n"
                    continue
                if "_result" in event:
                    ai_full, ai_sources = event["_result"]
                    break
                yield f"data: {json.dumps(event)}\n\n"

            ai_full = (ai_full or "").strip()
            if not ai_full:
                raise RuntimeError("Model returned an empty response.")

            await asyncio.to_thread(
                _insert_message,
                db,
                athlete_id,
                conversation_id,
                "ai",
                ai_full,
                None,
            )

            try:
                disconnected = await request.is_disconnected()
            except Exception:
                disconnected = False

            if not disconnected:
                chunk_size = 600
                for i in range(0, len(ai_full), chunk_size):
                    chunk = ai_full[i : i + chunk_size]
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                yield f"data: {json.dumps({'sources': ai_sources or []})}\n\n"
                recent_history = _load_conversation_history(db, athlete_id, conversation_id, limit=10)
                mem_task = asyncio.create_task(
                    _run_memory_extraction(
                        athlete_id,
                        recent_history,
                        db,
                        config.gemini_analysis_model,
                    )
                )
                title_task = asyncio.create_task(
                    _run_conversation_title(
                        db,
                        athlete_id,
                        conversation_id,
                        config.gemini_model,
                    )
                )
                _stream_bg_tasks.update({mem_task, title_task})
                mem_task.add_done_callback(_stream_bg_tasks.discard)
                title_task.add_done_callback(_stream_bg_tasks.discard)
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
