"""Timed notifications: morning readiness, evening debrief digest (and debriefs held back by
quiet hours), missed key session, weekly summary, sync problems.

`notification_loop` ticks every few minutes in every API replica. Each send is claimed in
notification_log first (athlete, kind, key), so replicas and restarts never double-send.
Due-time checks use the athlete's local time (athletes.timezone_offset_min) and a window
after the chosen time, so a tick that lands a few minutes late still sends.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services import coach_notifications as cn
from app.services import notification_prefs as np
from app.services.time_utils import coerce_timezone_offset_min, local_datetime_from_timezone_offset

logger = logging.getLogger(__name__)

TICK_SECONDS = 300
WINDOW_MIN = 60
KEY_ZONES = {"Threshold", "VO2Max", "Anaerobic", "SweetSpot"}
KEY_MIN_TSS = 80
STALE_HOURS = 48


# --- timing helpers (pure) ---------------------------------------------------------------

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(local_now: datetime, at: str, window_min: int = WINDOW_MIN) -> bool:
    """local_now is within [at, at + window) on its own day."""
    now_m = local_now.hour * 60 + local_now.minute
    start = _minutes(at)
    return start <= now_m < start + window_min


def weekly_due(prefs: dict, local_now: datetime) -> bool:
    day = np.option(prefs, "weekly")
    if day == "Mon":
        return local_now.weekday() == 0 and in_window(local_now, "07:00")
    return local_now.weekday() == 6 and in_window(local_now, "18:00")


def missed_check_day(prefs: dict, local_now: datetime) -> Optional[date]:
    """Which day's sessions to check now: yesterday at 07:00 ('morning'), today at 20:00 ('evening')."""
    if np.option(prefs, "missed") == "evening":
        return local_now.date() if in_window(local_now, "20:00") else None
    return local_now.date() - timedelta(days=1) if in_window(local_now, "07:00") else None


def is_key_session(plan: dict) -> bool:
    return plan.get("primary_zone") in KEY_ZONES or int(plan.get("target_tss") or 0) >= KEY_MIN_TSS


def last_completed_week_end(today: date) -> date:
    """Weeks run Sunday → Saturday in the app, so the summary covers the week that ended on
    the most recent Saturday (yesterday on Sunday evening, two days ago on Monday morning)."""
    return today - timedelta(days=(today.weekday() - 5) % 7 or 7)


def iso_week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# --- loop --------------------------------------------------------------------------------

async def notification_loop() -> None:
    await asyncio.sleep(30)  # let startup finish
    while True:
        try:
            await asyncio.to_thread(run_tick)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(TICK_SECONDS)


def run_tick(now_utc: Optional[datetime] = None) -> None:
    """One pass over athletes that can receive push."""
    db = cn.admin_db()
    now_utc = now_utc or datetime.now(timezone.utc)
    tokens = db.table("push_tokens").select("athlete_id").execute().data or []
    athlete_ids = sorted({t["athlete_id"] for t in tokens})
    if not athlete_ids:
        return
    rows = db.table("athletes").select("id,timezone_offset_min,notification_settings").in_("id", athlete_ids).execute().data or []
    for a in rows:
        try:
            tick_athlete(db, a, now_utc)
        except Exception:
            logger.warning("[notify] tick failed for %s", a.get("id"), exc_info=True)


def tick_athlete(db: Any, athlete: dict, now_utc: datetime) -> None:
    aid = athlete["id"]
    prefs = np.effective(athlete.get("notification_settings"))
    offset = coerce_timezone_offset_min(athlete.get("timezone_offset_min"))
    local_now = local_datetime_from_timezone_offset(offset, now_utc)
    quiet = np.in_quiet_hours(prefs, local_now)

    if not quiet:
        send_held_debriefs(db, aid, prefs, local_now)
    ready_at = np.option(prefs, "ready") or "07:00"
    if np.push_enabled(prefs, "ready") and in_window(local_now, ready_at) and not quiet:
        send_readiness(db, aid, local_now, ready_at)
    if np.push_enabled(prefs, "missed"):
        day = missed_check_day(prefs, local_now)
        if day:
            send_missed(db, aid, prefs, day, local_now)
    if np.push_enabled(prefs, "weekly") and weekly_due(prefs, local_now):
        send_weekly(db, aid, prefs, local_now)
    if np.push_enabled(prefs, "sync") and in_window(local_now, "09:00") and not quiet:
        send_sync_problem(db, aid, local_now, now_utc)


# --- debriefs held back (evening digest / quiet hours) --------------------------------------

def send_held_debriefs(db: Any, aid: str, prefs: dict, local_now: datetime) -> None:
    """Debrief threads created without a push: pushed at 19:00 for the evening digest, or as
    soon as quiet hours end for 'right away'."""
    if not np.push_enabled(prefs, "debrief"):
        return
    evening = np.option(prefs, "debrief") == "evening"
    if evening and not in_window(local_now, "19:00"):
        return
    since = (datetime.now(timezone.utc) - timedelta(hours=18)).isoformat()
    held = (
        db.table("notification_log")
        .select("id,conversation_id,created_at")
        .eq("athlete_id", aid)
        .eq("kind", "debrief")
        .eq("pushed", False)
        .gte("created_at", since)
        .not_.is_("conversation_id", "null")
        .order("created_at")
        .execute()
    ).data or []
    if not held:
        return
    key = f"{local_now.date().isoformat()}-{held[-1]['id']}"
    if not cn.claim(aid, "debrief_digest", key):
        return
    latest = held[-1]["conversation_id"]
    conv = db.table("coach_conversations").select("title,context").eq("id", latest).limit(1).execute().data or [{}]
    title = (conv[0].get("context") or {}).get("title") or "your workout"
    msg = db.table("coach_messages").select("content").eq("conversation_id", latest).order("created_at").limit(1).execute().data or [{}]
    n = len(held)
    sent = cn.push_thread(
        db,
        aid,
        type_id="debrief",
        conversation_id=latest,
        title=f"Coach · {title}" if n == 1 else f"Coach · {n} workout debriefs",
        body=cn.first_sentence(msg[0].get("content") or "") if n == 1 else f"Notes on {title} and {n - 1} more. Tap to read.",
        quick_replies=cn.DEBRIEF_QUICK_REPLIES if n == 1 else None,
        prefs=prefs,
        ignore_timing=True,
    )
    if sent:
        for h in held:
            cn.mark_log(h["id"], pushed=True)


# --- morning readiness -------------------------------------------------------------------

def _readiness_label(score: float) -> str:
    if score >= 67:
        return "ready to train"
    if score >= 34:
        return "train as planned"
    return "take it easy"


def readiness_should_wait(local_now: datetime, at: str, has_score: bool) -> bool:
    """Without today's score yet, wait for the sleep sync, except in the window's last 10 minutes."""
    if has_score:
        return False
    elapsed = local_now.hour * 60 + local_now.minute - _minutes(at)
    return elapsed < WINDOW_MIN - 10


def send_readiness(db: Any, aid: str, local_now: datetime, at: str) -> None:
    from app.services.push import send_push_to_athlete

    today = local_now.date().isoformat()
    bio = db.table("biometrics").select("readiness_score,recovery_score,hrv_rmssd,sleep_duration_min").eq("athlete_id", aid).eq("date", today).limit(1).execute().data or []
    score = (bio[0].get("readiness_score") or bio[0].get("recovery_score")) if bio else None
    if readiness_should_wait(local_now, at, score is not None):
        return
    if not cn.claim(aid, "ready", today):
        return
    plans = db.table("training_plans").select("title,duration_min,status").eq("athlete_id", aid).eq("planned_date", today).execute().data or []
    session = next((p for p in plans if p.get("status") != "done"), None)
    title = f"Readiness {round(float(score))} · {_readiness_label(float(score))}" if score is not None else "Good morning"
    body = (
        f"Today: {session['title']}, {int(session.get('duration_min') or 0)} min."
        if session
        else "Nothing planned today. Rest well."
    )
    if score is None:
        body += " Your sleep hasn't synced yet."
    send_push_to_athlete(athlete_id=aid, title=title, body=body, db=db, data={"url": "/readiness", "type": "ready"})


# --- missed key session -------------------------------------------------------------------

async def _compose(aid: str, directive: str) -> Optional[str]:
    from app.services.ai_coach import COACH_FAILURE_REPLIES, get_coach_response

    try:
        reply, _ = await asyncio.to_thread(
            get_coach_response,
            athlete_id=aid,
            message=f"{cn.PUSH_CHANNEL_NOTE}\n\n{directive}",
            current_tss=0.0,
            db=cn.admin_db(),
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


def send_missed(db: Any, aid: str, prefs: dict, day: date, local_now: datetime) -> None:
    plans = (
        db.table("training_plans")
        .select("id,title,planned_date,duration_min,target_tss,primary_zone,status,sport")
        .eq("athlete_id", aid)
        .eq("planned_date", day.isoformat())
        .in_("status", ["planned", "modified"])
        .execute()
    ).data or []
    for p in [p for p in plans if is_key_session(p)]:
        log_id = cn.claim(aid, "missed", p["id"])
        if not log_id:
            continue
        upcoming = (
            db.table("training_plans")
            .select("title,planned_date,target_tss")
            .eq("athlete_id", aid)
            .gt("planned_date", day.isoformat())
            .lte("planned_date", (day + timedelta(days=7)).isoformat())
            .order("planned_date")
            .execute()
        ).data or []
        weekday = f"{datetime.fromisoformat(day.isoformat()):%A}"
        reply = asyncio.run(
            _compose(
                aid,
                f"[SYSTEM: The athlete missed a key session: {p['title']} ({p.get('sport')}, "
                f"{p.get('duration_min')} min, {p.get('target_tss')} TSS) planned for {weekday} {day.isoformat()}. "
                f"Their next 7 days: {json.dumps(upcoming)}. Write a short note: no guilt, whether it's worth "
                "making up, and one concrete idea for where it could fit (or to let it go). End with one short "
                "question. Reply with only your <response> block; no tools.]",
            )
        )
        if not reply:
            cn.release(log_id)
            continue
        context = {
            "kind": "plan",
            "id": p["id"],
            "title": p["title"],
            "meta": f"{weekday[:3]} {day.day} {day:%b} · not recorded",
            "href": f"/plan?session={p['id']}",
        }
        cid = cn.create_coach_thread(
            aid, title=f"{weekday}'s {p['title']}", trigger="missed", context=context, message=reply,
            quick_replies=["Add it later this week", "Skip it"],
        )
        pushed = cn.push_thread(
            db, aid, type_id="missed", conversation_id=cid, title=f"Coach · Missed {p['title']}",
            body=cn.first_sentence(reply), quick_replies=["Add it later this week", "Skip it"], prefs=prefs,
        )
        cn.mark_log(log_id, conversation_id=cid, pushed=pushed)


# --- weekly summary ----------------------------------------------------------------------

def week_numbers(db: Any, aid: str, start: date, end: date) -> dict:
    s, e = start.isoformat(), end.isoformat()
    loads = db.table("tss_history").select("date,daily_tss,ctl,atl,tsb").eq("athlete_id", aid).gte("date", s).lte("date", e).order("date").execute().data or []
    plans = db.table("training_plans").select("target_tss,status,completed_workout_id").eq("athlete_id", aid).gte("planned_date", s).lte("planned_date", e).execute().data or []
    bio = db.table("biometrics").select("sleep_duration_min,hrv_rmssd").eq("athlete_id", aid).gte("date", s).lte("date", e).execute().data or []
    tss = round(sum(float(r.get("daily_tss") or 0) for r in loads))
    planned = round(sum(float(p.get("target_tss") or 0) for p in plans))
    sleeps = [float(b["sleep_duration_min"]) for b in bio if b.get("sleep_duration_min")]
    ctl_change = round(float(loads[-1]["ctl"]) - float(loads[0]["ctl"]), 1) if len(loads) >= 2 and loads[0].get("ctl") is not None else None
    return {
        "tss": tss,
        "planned_tss": planned,
        "pct_of_plan": round(tss / planned * 100) if planned else None,
        "sessions": len(plans),
        "sessions_linked": sum(1 for p in plans if p.get("completed_workout_id")),
        "sessions_done": sum(1 for p in plans if p.get("status") == "done"),
        "fitness_change": ctl_change,
        "form": round(float(loads[-1]["tsb"]), 1) if loads and loads[-1].get("tsb") is not None else None,
        "avg_sleep_min": round(sum(sleeps) / len(sleeps)) if sleeps else None,
    }


def send_weekly(db: Any, aid: str, prefs: dict, local_now: datetime) -> None:
    end = last_completed_week_end(local_now.date())
    start = end - timedelta(days=6)
    log_id = cn.claim(aid, "weekly", iso_week_key(end))
    if not log_id:
        return
    nums = week_numbers(db, aid, start, end)
    nxt = (
        db.table("training_plans")
        .select("title,planned_date,target_tss")
        .eq("athlete_id", aid)
        .gt("planned_date", end.isoformat())
        .lte("planned_date", (end + timedelta(days=7)).isoformat())
        .order("planned_date")
        .execute()
    ).data or []
    reply = asyncio.run(
        _compose(
            aid,
            f"[SYSTEM: Weekly summary for {start:%a %d %b} – {end:%a %d %b}. Numbers: {json.dumps(nums)}. "
            f"Next week's plan: {json.dumps(nxt)}. Write 2-3 sentences: how the week went against the plan, "
            "one thing to protect next week (sleep, recovery, a key session). Quote numbers only from the data "
            "above. Reply with only your <response> block; no tools.]",
        )
    )
    if not reply:
        cn.release(log_id)
        return
    meta = [f"{nums['tss']} TSS"]
    if nums["pct_of_plan"] is not None:
        diff = nums["pct_of_plan"] - 100
        meta.append(f"{abs(diff)}% {'over' if diff > 0 else 'under'} plan" if diff else "on plan")
    if nums["sessions"]:
        meta.append(f"{nums['sessions_done']} of {nums['sessions']} sessions done")
    label = f"{start.day} {start:%b} – {end.day} {end:%b}"
    context = {"kind": "week", "id": iso_week_key(end), "title": f"Your week · {label}", "meta": " · ".join(meta), "href": "/trends"}
    cid = cn.create_coach_thread(
        aid, title=f"Your week · {label}", trigger="weekly", context=context, message=reply,
        quick_replies=["What's next week?", "Thanks"],
    )
    pushed = cn.push_thread(
        db, aid, type_id="weekly", conversation_id=cid, title=f"Coach · Your week · {label}",
        body=cn.first_sentence(reply), quick_replies=["What's next week?", "Thanks"], prefs=prefs,
    )
    cn.mark_log(log_id, conversation_id=cid, pushed=pushed)


# --- sync problems -----------------------------------------------------------------------

PROVIDER_NAMES = {"garmin": "Garmin", "whoop": "WHOOP", "strava": "Strava", "intervals_icu": "Intervals.icu"}


def send_sync_problem(db: Any, aid: str, local_now: datetime, now_utc: datetime) -> None:
    """A connected app but no workouts and no daily data for STALE_HOURS. At most every 3 days."""
    from app.services.push import send_push_to_athlete

    providers = [r["provider"] for r in (db.table("oauth_tokens").select("provider").eq("athlete_id", aid).execute().data or [])]
    providers = [p for p in providers if p in PROVIDER_NAMES]
    if not providers:
        return
    cutoff = now_utc - timedelta(hours=STALE_HOURS)
    recent_w = db.table("workouts").select("id").eq("athlete_id", aid).gte("started_at", cutoff.isoformat()).limit(1).execute().data or []
    recent_b = db.table("biometrics").select("id").eq("athlete_id", aid).gte("date", cutoff.date().isoformat()).limit(1).execute().data or []
    if recent_w or recent_b:
        return
    bucket = local_now.date().toordinal() // 3
    if not cn.claim(aid, "sync", str(bucket)):
        return
    names = " and ".join(PROVIDER_NAMES[p] for p in providers)
    send_push_to_athlete(
        athlete_id=aid,
        title=f"{names} stopped sending data",
        body=f"Nothing new for {STALE_HOURS // 24} days. Open Connected apps to reconnect.",
        db=db,
        data={"url": "/profile/connections", "type": "sync"},
    )
