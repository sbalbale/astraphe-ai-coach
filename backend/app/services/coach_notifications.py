"""Coach-started threads and the push notifications that open them.

A notification here is always: (1) a claim in notification_log, so several API replicas or
a re-sync never send it twice; (2) a new coach conversation (started_by='coach') with a
context card and the coach's opening message plus quick replies; (3) a push whose tap
opens /chat?conversation=<id>. The push is skipped (the thread still appears, unread)
when that type is off, during quiet hours, or when the athlete picked a digest time; the
scheduler sends those later (see notification_scheduler).

Post-workout debrief replaces the Photon text: the same note goes to the app, and is only
also texted while the athlete's "texts" setting is still active.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings
from app.services import notification_prefs
from app.services.time_utils import fetch_athlete_timezone_offset_min, local_datetime_from_timezone_offset

logger = logging.getLogger(__name__)

DEBRIEF_QUICK_REPLIES = ["Felt good", "Legs were heavy", "Cut it short"]

PUSH_CHANNEL_NOTE = (
    "[CHANNEL: This message opens a coach thread from a phone notification; the first line "
    "shows in the notification. Write 2-3 short sentences: what they actually did with one "
    "concrete number, one thing worth noting, and end with one short question. No greeting, "
    "no headings, tables or bullet lists.]"
)


# --- small helpers -----------------------------------------------------------------------

def admin_db():
    from app.dependencies import get_admin_db

    return get_admin_db()


def load_prefs(db: Any, athlete_id: str) -> dict:
    try:
        res = db.table("athletes").select("notification_settings").eq("id", athlete_id).maybe_single().execute()
        return notification_prefs.effective((res.data or {}).get("notification_settings"))
    except Exception:
        return notification_prefs.effective(None)


def local_now(db: Any, athlete_id: str, now: Optional[datetime] = None) -> datetime:
    return local_datetime_from_timezone_offset(fetch_athlete_timezone_offset_min(db, athlete_id), now)


def claim(athlete_id: str, kind: str, key: str) -> Optional[str]:
    """Insert the notification_log row; returns its id, or None if it was already sent."""
    try:
        res = (
            admin_db()
            .table("notification_log")
            .upsert(
                {"athlete_id": athlete_id, "kind": kind, "dedupe_key": key},
                on_conflict="athlete_id,kind,dedupe_key",
                ignore_duplicates=True,
            )
            .execute()
        )
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        logger.warning("[notify] claim failed %s/%s: %r", kind, key, e)
        return None


def release(log_id: str) -> None:
    try:
        admin_db().table("notification_log").delete().eq("id", log_id).execute()
    except Exception:
        traceback.print_exc()


def release_for_retry(athlete_id: str, kind: str, key: str, log_id: str, max_attempts: int = 2) -> bool:
    """Composing the note failed. Release the claim so a later tick tries again, unless this
    notification already used max_attempts; then the claim is kept (nothing is sent), so an
    LLM outage can't turn into a model call every tick. Each failure leaves a
    '<kind>_failed' marker row. Returns True when released for another try."""
    for n in range(1, max_attempts):
        if claim(athlete_id, f"{kind}_failed", f"{key}#{n}"):
            release(log_id)
            return True
    return False


def mark_log(log_id: str, **fields: Any) -> None:
    try:
        admin_db().table("notification_log").update(fields).eq("id", log_id).execute()
    except Exception:
        traceback.print_exc()


def fmt_duration(seconds: Any) -> str:
    m = int(round(float(seconds or 0) / 60))
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}" if m % 60 else f"{m // 60}h"


def first_sentence(text: str, limit: int = 180) -> str:
    from app.services.text_format import markdown_to_plain_text

    plain = " ".join(markdown_to_plain_text(text or "").split())
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"


# --- threads -----------------------------------------------------------------------------

def create_coach_thread(
    athlete_id: str,
    *,
    title: str,
    trigger: str,
    context: Optional[dict],
    message: str,
    quick_replies: Optional[list[str]] = None,
) -> str:
    """A coach-started conversation with its opening message. Written with the service role
    (it happens outside any request), scoped to the athlete explicitly."""
    db = admin_db()
    now = datetime.now(timezone.utc).isoformat()
    conv = (
        db.table("coach_conversations")
        .insert(
            {
                "athlete_id": athlete_id,
                "title": title[:120],
                "started_by": "coach",
                "trigger": trigger,
                "context": context,
                "unread": True,
                "updated_at": now,
            }
        )
        .execute()
    )
    cid = conv.data[0]["id"]
    db.table("coach_messages").insert(
        {
            "athlete_id": athlete_id,
            "conversation_id": cid,
            "role": "ai",
            "content": message,
            "image_urls": [],
            "quick_replies": (quick_replies or [])[:4],
        }
    ).execute()
    return cid


def push_thread(
    db: Any,
    athlete_id: str,
    *,
    type_id: str,
    conversation_id: str,
    title: str,
    body: str,
    quick_replies: Optional[list[str]] = None,
    prefs: Optional[dict] = None,
    now: Optional[datetime] = None,
    ignore_timing: bool = False,
) -> bool:
    """Push that opens the thread. Returns False (nothing sent) when the type is off, in quiet
    hours, or (unless ignore_timing) when the athlete chose a later digest for this type."""
    from app.services.push import send_push_to_athlete

    prefs = prefs or load_prefs(db, athlete_id)
    if not notification_prefs.push_enabled(prefs, type_id):
        return False
    if notification_prefs.in_quiet_hours(prefs, local_now(db, athlete_id, now)):
        return False
    if not ignore_timing and type_id == "debrief" and notification_prefs.option(prefs, "debrief") == "evening":
        return False
    sent = send_push_to_athlete(
        athlete_id=athlete_id,
        title=title,
        body=body,
        db=admin_db(),
        data={
            "url": f"/chat?conversation={conversation_id}",
            "type": type_id,
            "conversation_id": conversation_id,
            # Up to two become notification actions (web push supports two).
            "quick_replies": json.dumps((quick_replies or [])[:2]),
        },
    )
    return sent > 0


# --- post-workout debrief ----------------------------------------------------------------

def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def debrief_eligible(row: dict, now: Optional[datetime] = None) -> bool:
    """Recent enough and long enough (history backfills and re-syncs never notify)."""
    if (row.get("duration_seconds") or 0) < settings.PHOTON_MIN_WORKOUT_MINUTES * 60:
        return False
    ended = _parse_ts(row.get("ended_at")) or _parse_ts(row.get("started_at"))
    if ended is None:
        return False
    now = now or datetime.now(timezone.utc)
    return timedelta(0) <= now - ended <= timedelta(hours=settings.PHOTON_WORKOUT_MAX_AGE_HOURS)


def workout_context(db: Any, athlete_id: str, w: dict) -> dict:
    """Context card: title + 'Mon 2 Nov · 1h 25 · 92 TSS · 100% of plan'."""
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    start = _parse_ts(w.get("started_at"))
    parts = []
    if start:
        d = local_datetime_from_timezone_offset(offset, start)
        parts.append(f"{d:%a} {d.day} {d:%b}")
    parts.append(fmt_duration(w.get("duration_seconds")))
    if w.get("tss") is not None:
        parts.append(f"{round(float(w['tss']))} TSS")
    try:
        plan = (
            db.table("training_plans")
            .select("title,target_tss")
            .eq("athlete_id", athlete_id)
            .eq("completed_workout_id", w["id"])
            .limit(1)
            .execute()
        ).data or []
    except Exception:
        plan = []
    if plan and plan[0].get("target_tss") and w.get("tss") is not None:
        parts.append(f"{round(float(w['tss']) / float(plan[0]['target_tss']) * 100)}% of plan")
    return {
        "kind": "workout",
        "id": w["id"],
        "title": w.get("title") or "Workout",
        "meta": " · ".join(p for p in parts if p),
        "href": f"/training?workout_id={w['id']}",
        "planned_title": plan[0]["title"] if plan else None,
    }


async def _compose_debrief(db: Any, athlete_id: str, w: dict, context: dict) -> Optional[str]:
    from app.services.ai_coach import COACH_FAILURE_REPLIES, get_coach_response
    from app.services.messaging import _lookup_workout_summary

    summary = await asyncio.to_thread(_lookup_workout_summary, db, athlete_id, w["id"])
    planned = f" It completes the planned session '{context['planned_title']}'." if context.get("planned_title") else ""
    directive = (
        f"{PUSH_CHANNEL_NOTE}\n\n[SYSTEM: The athlete just finished a {w.get('sport') or 'workout'} "
        f"('{w.get('title') or 'workout'}').{planned} Its data is below, already looked up. Write the "
        "post-workout debrief. Reply with only your <response> block; no tools.]\n"
        f"[WORKOUT DATA]\n{summary or json.dumps({k: w.get(k) for k in ('sport', 'title', 'duration_seconds', 'tss')})}"
    )
    try:
        reply, _ = await asyncio.to_thread(
            get_coach_response,
            athlete_id=athlete_id,
            message=directive,
            current_tss=0.0,
            db=db,
            conversation_id=None,
            model_name=None,
            timezone_offset_min=None,
            tools_enabled=False,
        )
    except Exception:
        traceback.print_exc()
        return None
    if not (reply or "").strip() or reply.strip() in COACH_FAILURE_REPLIES:
        return None
    return reply.strip()


async def post_workout_debrief(db: Any, athlete_id: str, workout_id: str) -> Optional[str]:
    """Coach debrief thread (+ push, + text while texts are still on) for a just-synced workout.
    Never raises; returns the conversation id when a thread was created."""
    try:
        prefs = await asyncio.to_thread(load_prefs, db, athlete_id)
        texts_on = (
            prefs.get("texts") == "active"
            and _photon_configured()
            and athlete_id == settings.PHOTON_ATHLETE_ID
        )
        if not prefs["types"]["debrief"]["on"] and not texts_on:
            return None
        res = await asyncio.to_thread(
            lambda: db.table("workouts")
            .select("id,sport,title,started_at,ended_at,duration_seconds,tss,notified_at")
            .eq("id", workout_id)
            .eq("athlete_id", athlete_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows or rows[0].get("notified_at") or not debrief_eligible(rows[0]):
            return None
        w = rows[0]
        log_id = await asyncio.to_thread(claim, athlete_id, "debrief", workout_id)
        if not log_id:
            return None

        context = await asyncio.to_thread(workout_context, db, athlete_id, w)
        reply = await _compose_debrief(db, athlete_id, w, context)
        if not reply:
            await asyncio.to_thread(release, log_id)  # allow a retry on the next sync
            return None

        cid = None
        if prefs["types"]["debrief"]["on"]:
            cid = await asyncio.to_thread(
                create_coach_thread,
                athlete_id,
                title=f"{context['title']} debrief",
                trigger="debrief",
                context=context,
                message=reply,
                quick_replies=DEBRIEF_QUICK_REPLIES,
            )
            pushed = await asyncio.to_thread(
                push_thread,
                db,
                athlete_id,
                type_id="debrief",
                conversation_id=cid,
                title=f"Coach · {context['title']}",
                body=first_sentence(reply),
                quick_replies=DEBRIEF_QUICK_REPLIES,
                prefs=prefs,
            )
            await asyncio.to_thread(mark_log, log_id, conversation_id=cid, pushed=pushed)

        # Still texting while the athlete hasn't switched texts off (one note, both channels).
        try:
            await asyncio.to_thread(
                lambda: admin_db().table("workouts").update({"notified_at": datetime.now(timezone.utc).isoformat()}).eq("id", workout_id).execute()
            )
        except Exception:
            traceback.print_exc()
        if texts_on:
            from app.services import photon

            await photon.send_text(reply)
        return cid
    except Exception:
        traceback.print_exc()
        return None


def _photon_configured() -> bool:
    from app.services import photon

    return photon.is_configured()
