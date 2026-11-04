from fastapi import APIRouter, HTTPException, Depends, UploadFile, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pathlib import Path
from pydantic import BaseModel, field_validator
from typing import Any, Optional, List
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
from app.services import coach_progress
from app.dependencies import (
    get_current_athlete,
    get_user_config,
    get_user_db,
    require_ai_rate_limit,
    UserConfig,
)

_ALLOWED_DOC_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".docx"}
# Text kept per attached document (parsers stop at the same size), and documents per message.
_MAX_DOC_CHARS = 30000
_MAX_DOCS_PER_MESSAGE = 3
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


class ChatDocument(BaseModel):
    """A document the client parsed via /upload-document and attaches to a message."""
    name: str
    content: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return (v or "document").strip()[:200] or "document"

    @field_validator("content")
    @classmethod
    def cap_content(cls, v: str) -> str:
        return (v or "")[:_MAX_DOC_CHARS]


class ChatMessage(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    recent_tss: Optional[float] = 0.0
    image_urls: Optional[List[str]] = None
    documents: Optional[List[ChatDocument]] = None
    # Legacy: text only, no file names.
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
        if len(v) > _MAX_DOCS_PER_MESSAGE:
            raise ValueError("Max 3 documents per message")
        return [c[:_MAX_DOC_CHARS] for c in v]

    @field_validator("documents")
    @classmethod
    def validate_documents(cls, v: Optional[List["ChatDocument"]]) -> Optional[List["ChatDocument"]]:
        if v is not None and len(v) > _MAX_DOCS_PER_MESSAGE:
            raise ValueError("Max 3 documents per message")
        return v


def _message_documents(payload: "ChatMessage") -> list[dict]:
    """Attached documents as [{name, kind, content}] (new `documents` plus legacy `document_contents`)."""
    docs: list[dict] = []
    for d in payload.documents or []:
        if d.content.strip():
            docs.append({"name": d.name, "kind": Path(d.name).suffix.lower().lstrip(".") or "file", "content": d.content})
    for i, content in enumerate(payload.document_contents or [], 1):
        if (content or "").strip():
            docs.append({"name": f"Document {i}", "kind": "file", "content": content})
    return docs[:_MAX_DOCS_PER_MESSAGE]


def _message_with_documents(message: str, docs: list[dict]) -> str:
    """What the model sees for this turn: each document's text, then the athlete's message."""
    if not docs:
        return message
    parts = [f"[ATTACHED DOCUMENT: {d['name']}]\n{d['content']}" for d in docs]
    return "\n\n".join(parts) + "\n\n[ATHLETE MESSAGE]\n" + message

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

def _require_own_conversation(db, athlete_id: str, conversation_id: Optional[str]) -> None:
    """
    404 unless the conversation belongs to this athlete. RLS on coach_messages only
    checks athlete_id, so without this a user could attach messages to someone else's
    conversation id (and the FK error would reveal whether an id exists).
    """
    if not conversation_id:
        return
    res = (
        db.table("coach_conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("athlete_id", athlete_id)
        .limit(1)
        .execute()
    )
    if not (getattr(res, "data", None) or []):
        raise HTTPException(status_code=404, detail="Conversation not found")


def _create_conversation(db, athlete_id: str, title: Optional[str]) -> str:
    res = db.table("coach_conversations").insert({
        "athlete_id": athlete_id,
        "title": title,
        "updated_at": _now_iso(),
    }).execute()
    if not res.data:
        raise RuntimeError("Failed to create conversation")
    return res.data[0]["id"]

def _touch_conversation(db, athlete_id: str, conversation_id: str, read: bool = False):
    update: dict[str, Any] = {"updated_at": _now_iso()}
    if read:
        update["unread"] = False  # the athlete replied, so they've seen it
    db.table("coach_conversations").update(update).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()

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

def _ai_message_writer(db):
    """
    Client for coach/system turns: the service role. User sessions will only be
    allowed to insert role='user', so nobody can plant fake coach or system turns in
    their own prompt history. (Audit X-L9; the RLS check is a post-deploy migration.)
    """
    from app.dependencies import get_admin_db

    return get_admin_db()


def _insert_message(
    db,
    athlete_id: str,
    conversation_id: str,
    role: str,
    content: str,
    image_urls: Optional[List[str]] = None,
    documents: Optional[list[dict]] = None,
):
    writer = db if role == "user" else _ai_message_writer(db)
    row = {
        "athlete_id": athlete_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "image_urls": image_urls or [],
    }
    if documents:
        # Kept with the message so later turns (and the chat after a reload) still have them.
        row["attachments"] = documents
    writer.table("coach_messages").insert(row).execute()
    if role == "user":
        title_seed = content if (content or "").strip() or not documents else documents[0]["name"]
        _maybe_set_conversation_title(db, athlete_id, conversation_id, _generate_conversation_title(title_seed, image_urls=image_urls))
    _touch_conversation(db, athlete_id, conversation_id, read=(role == "user"))

from app.services.tiers import has_premium_access

router = APIRouter(prefix="/v1/coach", tags=["AI Coach"])

def _require_premium(config: UserConfig):
    if not has_premium_access(config.tier):
        raise HTTPException(status_code=403, detail="Premium membership required for AI Coach.")


@router.get("/conversations")
def list_conversations(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    db = Depends(get_user_db),
):
    _require_premium(config)
    res = (
        db.table("coach_conversations")
        .select("id,title,created_at,updated_at,started_by,trigger,context,unread,coach_messages(count)")
        .eq("athlete_id", athlete_id)
        .order("updated_at", desc=True)
        .limit(_CONVERSATION_SCAN)
        .execute()
    )
    return {"status": "success", "conversations": _with_messages(res.data or [])[:_CONVERSATION_LIST]}


_CONVERSATION_LIST = 50
# Read a few more than are listed: empty ones are dropped after the query.
_CONVERSATION_SCAN = 80


def _with_messages(rows: list[dict]) -> list[dict]:
    """Conversations that have at least one message. A chat is created before its first
    message is sent (to upload photos into it), so an abandoned attempt leaves an empty
    "New chat" behind; those stay out of the history. The count comes from the embedded
    `coach_messages(count)`; a row without it is kept."""
    out = []
    for r in rows:
        r = dict(r)
        embedded = r.pop("coach_messages", None)
        count = embedded[0].get("count") if isinstance(embedded, list) and embedded and isinstance(embedded[0], dict) else None
        if count is None or count > 0:
            out.append(r)
    return out


@router.post("/conversations/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: str,
    athlete_id: str = Depends(get_current_athlete),
    db = Depends(get_user_db),
):
    """Clear the unread dot on a coach-started thread (the chat calls this when it opens one)."""
    db.table("coach_conversations").update({"unread": False}).eq("id", conversation_id).eq("athlete_id", athlete_id).execute()
    return {"status": "success"}


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
def get_conversation_messages(
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
        .select("id,role,content,image_urls,attachments,quick_replies,created_at")
        .eq("athlete_id", athlete_id)
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .limit(500)
        .execute()
    )
    messages = res.data or []
    for m in messages:
        # The client only shows a chip per document; the text stays server-side.
        m["attachments"] = [
            {"name": a.get("name") or "document", "kind": a.get("kind") or "file"}
            for a in (m.get("attachments") or [])
            if isinstance(a, dict)
        ]
        if m.get("role") == "ai":
            m["content"] = _strip_internal_reasoning(str(m.get("content") or ""))
    return {"status": "success", "messages": messages}

@router.get("/conversations/{conversation_id}/progress")
async def get_conversation_progress(
    conversation_id: str,
    visible: bool = False,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
):
    """
    Live steps ("started", "context_ready", "thinking", "tool" + name, "done") for the
    reply being generated by POST /message/async. Keyed by athlete, so it only ever
    returns the caller's own progress. Empty once it expires (10 min).

    visible=1 means the chat is on screen, so the reply needs no push (see
    coach_progress.mark_watching).
    """
    _require_premium(config)
    if visible:
        await coach_progress.mark_watching(athlete_id, conversation_id)
    return {"events": await coach_progress.read(athlete_id, conversation_id)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
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
    request: Request,
    file: UploadFile,
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
    _rl: None = Depends(require_ai_rate_limit),
    db = Depends(get_user_db),
):
    """
    Parse an uploaded PDF, Word (.docx), CSV or Excel file and return the extracted text.
    The client sends it back with the next message as `documents: [{name, content}]`.
    """
    _require_premium(config)
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_DOC_EXTENSIONS:
        if ext == ".doc":
            raise HTTPException(status_code=415, detail="Old Word (.doc) files aren't supported. Save it as .docx or PDF and try again.")
        raise HTTPException(status_code=415, detail=f"Unsupported file type '{ext}'. Use a PDF, Word (.docx), Excel or CSV file.")

    # Reject oversized uploads before buffering them: check the declared length, then
    # read at most one byte past the cap.
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > _MAX_DOC_BYTES + 64 * 1024:  # multipart overhead
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    file_bytes = await file.read(_MAX_DOC_BYTES + 1)
    if len(file_bytes) > _MAX_DOC_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        from app.services.file_parser import parse_document
        text = await asyncio.to_thread(parse_document, file_bytes, filename)
    except Exception as e:
        print(f"[coach.upload] parse failed file={filename!r}: {e!r}")
        raise HTTPException(status_code=422, detail="Couldn't read this document. Try a PDF, Word (.docx), Excel or CSV file.")

    if not (text or "").strip():
        raise HTTPException(status_code=422, detail="No text could be read from this document. If it's a scanned PDF, try a photo of the page instead.")

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
    reply_sink=None,
) -> None:
    """
    reply_sink: optional async callable(reply_text). When set (the Photon text
    channel), the reply is delivered through it instead of an app push notification.

    The async counterpart of chat_with_coach()'s body, minus the parts that
    have to happen before the HTTP response goes out (creating the
    conversation, inserting the user's message). Runs as a BackgroundTask —
    the client already has its response and may not be connected anymore —
    so every step below is best-effort: a failure here must still leave the
    athlete with *something* in coach_messages and, if possible, a push
    notification, rather than a silently stuck "thinking" placeholder.
    """
    # Progress events ("thinking", "tool") come from the worker thread; hand each to the
    # event loop so GET /conversations/{id}/progress can show what the coach is doing.
    loop = asyncio.get_running_loop()
    progress_futures: list = []

    def _progress(event: dict) -> None:
        try:
            progress_futures.append(
                asyncio.run_coroutine_threadsafe(
                    coach_progress.append(athlete_id, conversation_id, event), loop
                )
            )
        except Exception:
            pass

    try:
        await coach_progress.reset(athlete_id, conversation_id)
        await coach_progress.append(athlete_id, conversation_id, {"status": "started"})
    except Exception:
        pass

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
            progress_callback=_progress,
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

    # Let queued progress writes land before marking the reply done, so "done" is last.
    if progress_futures:
        await asyncio.gather(*(asyncio.wrap_future(fut) for fut in progress_futures), return_exceptions=True)

    try:
        _insert_message(db, athlete_id, conversation_id, role="ai", content=coach_reply, image_urls=None)
    except Exception:
        traceback.print_exc()
        return  # Nothing to notify/extract from if the reply itself never landed.

    try:
        await coach_progress.append(athlete_id, conversation_id, {"status": "done"})
    except Exception:
        pass

    # Deliver the reply first. Memory extraction and title generation are each a model call
    # (~10-30s together) that the athlete shouldn't have to wait on before being notified.
    if reply_sink is not None:
        try:
            await reply_sink(coach_reply)
        except Exception:
            traceback.print_exc()
    elif not await coach_progress.is_watching(athlete_id, conversation_id):
        try:
            from app.services.push import send_push_to_athlete
            from app.services.text_format import notification_preview

            preview = notification_preview(coach_reply or "")
            send_push_to_athlete(
                athlete_id=athlete_id,
                title="ASTRAPHE Coach",
                body=preview,
                db=db,
                data={"url": "/chat", "conversation_id": conversation_id, "type": "reply"},
                notification_type="reply",
            )
        except Exception:
            pass

    try:
        recent_history = await asyncio.to_thread(
            _load_conversation_history, db, athlete_id, conversation_id, 10
        )
        await _run_memory_extraction(athlete_id, recent_history, db, analysis_model_name)
    except Exception:
        pass

    await _run_conversation_title(db, athlete_id, conversation_id, model_name)


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
    _require_own_conversation(db, athlete_id, payload.conversation_id)
    conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
    docs = _message_documents(payload)
    _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls, documents=docs)
    # Clear the previous reply's steps before returning, so the first progress poll
    # never shows them.
    await coach_progress.reset(athlete_id, conversation_id)

    effective_message = _message_with_documents(payload.message, docs)

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
    _require_own_conversation(db, athlete_id, payload.conversation_id)
    try:
        conversation_id = payload.conversation_id or _create_conversation(db, athlete_id, title=None)
        docs = _message_documents(payload)
        _insert_message(db, athlete_id, conversation_id, role="user", content=payload.message, image_urls=payload.image_urls, documents=docs)

        # Prepend any uploaded document content to the effective message for the AI.
        effective_message = _message_with_documents(payload.message, docs)

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

            if not await coach_progress.is_watching(athlete_id, conversation_id):
                send_push_to_athlete(
                    athlete_id=athlete_id,
                    title="ASTRAPHE Coach",
                    body=notification_preview(coach_reply or ""),
                    db=db,
                    data={"url": "/chat", "type": "reply"},
                    notification_type="reply",
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
        raise HTTPException(status_code=500, detail="The coach couldn't reply. Please try again.") from e


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
    await asyncio.to_thread(_require_own_conversation, db, athlete_id, payload.conversation_id)

    async def event_generator():
        conversation_id = payload.conversation_id
        if not conversation_id:
            conversation_id = await asyncio.to_thread(_create_conversation, db, athlete_id, None)

        yield f"data: {json.dumps({'conversation_id': conversation_id, 'status': 'started'})}\n\n"

        docs = _message_documents(payload)
        await asyncio.to_thread(
            _insert_message,
            db,
            athlete_id,
            conversation_id,
            "user",
            payload.message,
            payload.image_urls,
            docs,
        )

        effective_message = _message_with_documents(payload.message, docs)

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
                recent_history = await asyncio.to_thread(_load_conversation_history, db, athlete_id, conversation_id, limit=10)
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
            print(f"[coach.stream] failed: {e!r}")
            yield f"data: {json.dumps({'error': 'The coach could not reply. Please try again.'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
