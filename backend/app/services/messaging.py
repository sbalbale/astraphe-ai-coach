"""Photon text channel for the AI coach.

Texts share the app's coach chat: they read and write the same coach_conversations /
coach_messages rows as /v1/coach/*, so a thread started on the phone shows up in the
app and vice versa. The coach itself is the same get_coach_response() the app uses.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings
from app.services import photon

logger = logging.getLogger(__name__)

PROVIDER = "photon"

# Appended to what the model sees (never stored in the chat history) so replies
# read like a text, not an app answer.
TEXT_CHANNEL_NOTE = (
    "[CHANNEL: This athlete is texting you over iMessage, not using the app. Reply in "
    "2-4 short conversational sentences. No tables, headings, or long bullet lists; "
    "offer to go deeper if they want more.]"
)

NEW_CHAT_COMMANDS = {"/new", "/new chat"}

# Serializes post-workout texts within one process (see maybe_text_workout).
_workout_text_lock = asyncio.Lock()

_inbound_times: deque[float] = deque()


def _rate_limited() -> bool:
    """Per-process cap on inbound messages per minute (single-user channel)."""
    now = time.monotonic()
    while _inbound_times and now - _inbound_times[0] > 60:
        _inbound_times.popleft()
    if len(_inbound_times) >= settings.PHOTON_MAX_INBOUND_PER_MINUTE:
        return True
    _inbound_times.append(now)
    return False


def claim_inbound(db: Any, message_id: str) -> bool:
    """True if this message id is new. The PK makes a re-delivery's insert fail."""
    try:
        db.table("messaging_events").insert({"provider": PROVIDER, "message_id": message_id}).execute()
        return True
    except Exception:
        return False


def _latest_conversation_id(db: Any, athlete_id: str) -> Optional[str]:
    res = (
        db.table("coach_conversations")
        .select("id")
        .eq("athlete_id", athlete_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0]["id"] if rows else None


def get_or_create_conversation(db: Any, athlete_id: str) -> str:
    """Continue the athlete's most recent chat (same thread as the app), or start one."""
    from app.routers.coach import _create_conversation

    return _latest_conversation_id(db, athlete_id) or _create_conversation(db, athlete_id, title=None)


NEW_CHAT_FALLBACK = "Started a new chat. What's on your mind?"


async def _opening_message(db: Any, athlete_id: str) -> Optional[str]:
    """The app's chat-open message (proactive anomaly warning, else a context-aware greeting)."""
    try:
        from app.services.ai_coach import build_initialization_message

        message, _is_proactive = await asyncio.to_thread(
            build_initialization_message, athlete_id, db, None, None
        )
        return (message or "").strip() or None
    except Exception:
        traceback.print_exc()
        return None


async def _start_new_chat(db: Any, athlete_id: str) -> None:
    """Create a fresh conversation (newest, so texts and the app both pick it up) and open it
    the way the app does. The opener is stored as the first coach message."""
    from app.routers.coach import _create_conversation, _insert_message

    conversation_id = await asyncio.to_thread(_create_conversation, db, athlete_id, None)
    opener = await _opening_message(db, athlete_id)
    if opener:
        await asyncio.to_thread(_insert_message, db, athlete_id, conversation_id, "ai", opener, None)
    await photon.send_text(opener or NEW_CHAT_FALLBACK)


async def handle_inbound_text(db: Any, sender: str, message_id: str, text: str) -> str:
    """Process one inbound text. Returns a short status string (used by the router/tests)."""
    if not photon.is_configured():
        return "not_configured"
    if not photon.is_allowed_sender(sender):
        logger.warning("[photon] dropped message from non-allow-listed sender")
        return "ignored_sender"
    body = (text or "").strip()
    if not body:
        return "empty"
    if not await asyncio.to_thread(claim_inbound, db, message_id):
        return "duplicate"
    if body.lower() in NEW_CHAT_COMMANDS:
        await _start_new_chat(db, settings.PHOTON_ATHLETE_ID)
        return "new_chat"
    if _rate_limited():
        await photon.send_text("You're sending messages faster than I can keep up. Give me a minute.")
        return "rate_limited"

    from app.routers.coach import _insert_message, _run_coach_response_and_notify

    athlete_id = settings.PHOTON_ATHLETE_ID
    conversation_id = await asyncio.to_thread(get_or_create_conversation, db, athlete_id)
    await asyncio.to_thread(_insert_message, db, athlete_id, conversation_id, "user", body, None)

    await _run_coach_response_and_notify(
        athlete_id,
        f"{TEXT_CHANNEL_NOTE}\n\n{body}",
        0.0,
        db,
        conversation_id,
        None,
        settings.GEMINI_ANALYSIS_MODEL,
        None,
        reply_sink=photon.send_text,
    )
    return "processed"


# ---------------------------------------------------------------------------
# Post-workout texts
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _workout_eligible(row: dict, now: Optional[datetime] = None) -> bool:
    """Recent enough, long enough, and not already texted about."""
    if row.get("notified_at"):
        return False
    if (row.get("duration_seconds") or 0) < settings.PHOTON_MIN_WORKOUT_MINUTES * 60:
        return False
    ended = _parse_ts(row.get("ended_at"))
    if ended is None:
        return False
    now = now or datetime.now(timezone.utc)
    return timedelta(0) <= now - ended <= timedelta(hours=settings.PHOTON_WORKOUT_MAX_AGE_HOURS)


def _claim_workout(db: Any, workout_id: str) -> bool:
    """Atomically set notified_at; only the caller that flips NULL -> now() gets True."""
    res = (
        db.table("workouts")
        .update({"notified_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", workout_id)
        .is_("notified_at", "null")
        .execute()
    )
    return bool(res.data)


def _release_workout(db: Any, workout_id: str) -> None:
    try:
        db.table("workouts").update({"notified_at": None}).eq("id", workout_id).execute()
    except Exception:
        traceback.print_exc()


async def maybe_text_workout(db: Any, athlete_id: str, workout_id: str) -> bool:
    """Text the athlete a post-workout note. Never raises; returns True if a text went out."""
    try:
        if not photon.is_configured() or athlete_id != settings.PHOTON_ATHLETE_ID:
            return False

        res = await asyncio.to_thread(
            lambda: db.table("workouts")
            .select("id,sport,title,duration_seconds,ended_at,notified_at")
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows or not _workout_eligible(rows[0]):
            return False
        if not await asyncio.to_thread(_claim_workout, db, workout_id):
            return False

        # Workouts that sync together are texted one at a time, in the order they were
        # claimed (asyncio.Lock is FIFO), so the bubbles arrive in order and each note can
        # see the previous one in the chat history instead of repeating it.
        async with _workout_text_lock:
            return await _compose_and_send_workout_text(db, athlete_id, workout_id, rows[0].get("sport"))
    except Exception:
        traceback.print_exc()
        return False


async def _compose_and_send_workout_text(db: Any, athlete_id: str, workout_id: str, sport: Optional[str]) -> bool:
    try:
        from app.routers.coach import _insert_message
        from app.services.ai_coach import get_coach_response

        conversation_id = await asyncio.to_thread(get_or_create_conversation, db, athlete_id)
        directive = (
            f"{TEXT_CHANNEL_NOTE}\n\n[SYSTEM: The athlete just finished workout id {workout_id} "
            f"({sport or 'workout'}). Look it up with get_workout_summary, then "
            "text them a short post-workout note: what they actually did, one thing worth "
            "noting, and one next step. Do not greet them or announce that you looked it up. "
            "If you already texted about another workout in this chat just now, don't repeat "
            "the advice you gave.]"
        )
        try:
            reply, _sources = await asyncio.to_thread(
                get_coach_response,
                athlete_id=athlete_id,
                message=directive,
                current_tss=0.0,
                db=db,
                conversation_id=conversation_id,
                model_name=None,
                timezone_offset_min=None,
            )
        except Exception:
            traceback.print_exc()
            await asyncio.to_thread(_release_workout, db, workout_id)  # allow a retry
            return False

        from app.services.ai_coach import COACH_FAILURE_REPLIES

        # The coach returns a canned apology instead of raising when it can't finish; that must
        # never be texted as if it were the post-workout note.
        if not (reply or "").strip() or reply.strip() in COACH_FAILURE_REPLIES:
            logger.warning("[photon] coach could not write the note for workout %s; will retry", workout_id)
            await asyncio.to_thread(_release_workout, db, workout_id)
            return False

        await asyncio.to_thread(_insert_message, db, athlete_id, conversation_id, "ai", reply, None)
        sent = await photon.send_text(reply)
        if not sent:
            logger.warning("[photon] post-workout text for %s was stored but not delivered", workout_id)
        return sent
    except Exception:
        traceback.print_exc()
        return False
