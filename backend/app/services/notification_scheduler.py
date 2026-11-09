"""Timed notifications: morning readiness (once last night's sleep is recorded), evening debrief digest (and debriefs held back by
quiet hours), weekly summary, sync problems.

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
from app.services.time_utils import coerce_timezone_offset_min, format_duration_min, local_datetime_from_timezone_offset

logger = logging.getLogger(__name__)

TICK_SECONDS = 300
WINDOW_MIN = 60
# Weekly notes are claimed only outside quiet hours, so their window is wider: quiet hours
# ending a little after 07:00 (or an 18:00 send with quiet hours starting soon after)
# still leave non-quiet ticks to send in.
LATE_WINDOW_MIN = 180
# Debriefs held for the 19:00 digest: everything since the previous day's window (a 20:30
# workout misses today's 19:00 window and goes out tomorrow).
HELD_LOOKBACK_HOURS = 36
# Morning readiness goes out at the first tick that finds last night's sleep recorded (and
# outside quiet hours), between these local times. Sleep that syncs in the afternoon gets no
# push; a late nap or a hand-logged night in the evening never counts as the morning one.
READY_FROM = "04:00"
READY_UNTIL = "12:00"
STALE_HOURS = 48
# Sync-problem alerts for one outage (since the last data arrived): at most this many,
# 3 days apart, then 6 days.
SYNC_MAX_ALERTS = 3
SYNC_FIRST_GAP_DAYS = 3
# Composing a weekly note with the LLM: at most this many tries per notification.
COMPOSE_MAX_ATTEMPTS = 2
PAGE_SIZE = 1000
ID_CHUNK = 200


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
        return local_now.weekday() == 0 and in_window(local_now, "07:00", LATE_WINDOW_MIN)
    return local_now.weekday() == 6 and in_window(local_now, "18:00", LATE_WINDOW_MIN)


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


def push_athlete_ids(db: Any) -> list[str]:
    """Every athlete with a push token (PostgREST caps a response at 1000 rows, so page)."""
    ids: set[str] = set()
    start = 0
    while True:
        page = (
            db.table("push_tokens").select("athlete_id").order("athlete_id")
            .range(start, start + PAGE_SIZE - 1).execute().data
        ) or []
        ids.update(t["athlete_id"] for t in page)
        if len(page) < PAGE_SIZE:
            return sorted(ids)
        start += PAGE_SIZE


def run_tick(now_utc: Optional[datetime] = None) -> None:
    """One pass over athletes that can receive push."""
    db = cn.admin_db()
    now_utc = now_utc or datetime.now(timezone.utc)
    athlete_ids = push_athlete_ids(db)
    for i in range(0, len(athlete_ids), ID_CHUNK):
        chunk = athlete_ids[i : i + ID_CHUNK]
        rows = db.table("athletes").select("id,timezone_offset_min,notification_settings").in_("id", chunk).execute().data or []
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

    # Everything is gated on quiet hours before it is claimed: a claim is final, so a send
    # attempted in quiet hours would be lost instead of going out at a later tick.
    if quiet:
        return
    send_held_debriefs(db, aid, prefs, local_now, now_utc)
    if np.push_enabled(prefs, "ready") and readiness_window(local_now):
        send_readiness(db, aid, local_now)
    if np.push_enabled(prefs, "weekly") and weekly_due(prefs, local_now):
        send_weekly(db, aid, prefs, local_now)
    if np.push_enabled(prefs, "sync") and in_window(local_now, "09:00"):
        send_sync_problem(db, aid, local_now, now_utc)


# --- debriefs held back (evening digest / quiet hours) --------------------------------------

def send_held_debriefs(db: Any, aid: str, prefs: dict, local_now: datetime, now_utc: Optional[datetime] = None) -> None:
    """Debrief threads created without a push: pushed at 19:00 for the evening digest, or as
    soon as quiet hours end for 'right away'. Looks back past the previous day's digest
    window, so a debrief created after 20:00 goes out in the next day's digest."""
    if not np.push_enabled(prefs, "debrief"):
        return
    evening = np.option(prefs, "debrief") == "evening"
    if evening and not in_window(local_now, "19:00"):
        return
    since = ((now_utc or datetime.now(timezone.utc)) - timedelta(hours=HELD_LOOKBACK_HOURS)).isoformat()
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


def readiness_window(local_now: datetime) -> bool:
    """Morning hours in which a newly recorded sleep sends the readiness push."""
    now_m = local_now.hour * 60 + local_now.minute
    return _minutes(READY_FROM) <= now_m < _minutes(READY_UNTIL)


def readiness_ready(row: Optional[dict]) -> bool:
    """Today's biometrics have last night's sleep and the readiness computed from it.
    (A readiness score alone isn't enough: it's computed from form even with no sleep.)"""
    return bool(row) and float(row.get("sleep_duration_min") or 0) > 0 and row.get("readiness_score") is not None


def send_readiness(db: Any, aid: str, local_now: datetime) -> None:
    """Sent once a day, as soon as last night's sleep is recorded (checked every tick)."""
    from app.services.push import send_push_to_athlete

    today = local_now.date().isoformat()
    bio = db.table("biometrics").select("readiness_score,sleep_duration_min").eq("athlete_id", aid).eq("date", today).limit(1).execute().data or []
    row = bio[0] if bio else None
    if not readiness_ready(row):
        return
    score = row.get("readiness_score")
    if not cn.claim(aid, "ready", today):
        return
    plans = db.table("training_plans").select("title,duration_min,status").eq("athlete_id", aid).eq("planned_date", today).execute().data or []
    session = next((p for p in plans if p.get("status") != "done"), None)
    title = f"Readiness {round(float(score))} · {_readiness_label(float(score))}"
    body = (
        f"Today: {session['title']}, {int(session.get('duration_min') or 0)} min."
        if session
        else "Nothing planned today. Rest well."
    )
    send_push_to_athlete(athlete_id=aid, title=title, body=body, db=db, data={"url": "/readiness", "type": "ready"})


# --- composing coach notes ----------------------------------------------------------------

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
        # Already in hours and minutes, so the summary never says "449 minutes".
        "avg_sleep": format_duration_min(sum(sleeps) / len(sleeps), "sleep") if sleeps else None,
    }


def send_weekly(db: Any, aid: str, prefs: dict, local_now: datetime) -> None:
    end = last_completed_week_end(local_now.date())
    start = end - timedelta(days=6)
    week_key = iso_week_key(end)
    log_id = cn.claim(aid, "weekly", week_key)
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
        cn.release_for_retry(aid, "weekly", week_key, log_id, COMPOSE_MAX_ATTEMPTS)
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

# Strava is not listed: the integration is disabled ("coming soon"), so a stale Strava
# token is not a problem the athlete can fix.
PROVIDER_NAMES = {"garmin": "Garmin", "whoop": "WHOOP", "intervals_icu": "Intervals.icu"}


def _parse_dt(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_data_at(db: Any, aid: str) -> Optional[datetime]:
    """When the latest workout started, or the end of the latest day with daily data
    (whichever is later)."""
    w = db.table("workouts").select("started_at").eq("athlete_id", aid).order("started_at", desc=True).limit(1).execute().data or []
    b = db.table("biometrics").select("date").eq("athlete_id", aid).order("date", desc=True).limit(1).execute().data or []
    day = _parse_dt(str(b[0].get("date"))[:10]) if b else None
    times = [t for t in (_parse_dt(w[0].get("started_at")) if w else None, day + timedelta(days=1) if day else None) if t]
    return max(times) if times else None


def sync_alert_due(previous: list[datetime], now_utc: datetime) -> bool:
    """previous = alerts already sent for this outage. Up to SYNC_MAX_ALERTS, backing off:
    3 days after the first, then 6 days after the second."""
    if len(previous) >= SYNC_MAX_ALERTS:
        return False
    if not previous:
        return True
    gap = timedelta(days=SYNC_FIRST_GAP_DAYS * 2 ** (len(previous) - 1)) - timedelta(hours=2)
    return now_utc - max(previous) >= gap


def send_sync_problem(db: Any, aid: str, local_now: datetime, now_utc: datetime) -> None:
    """A connected app but no workouts and no daily data for STALE_HOURS. Up to three alerts
    per outage (counted in notification_log since the last data arrived), then silence until
    data arrives again."""
    from app.services.push import send_push_to_athlete

    providers = [r["provider"] for r in (db.table("oauth_tokens").select("provider").eq("athlete_id", aid).execute().data or [])]
    providers = [p for p in providers if p in PROVIDER_NAMES]
    if not providers:
        return
    last = last_data_at(db, aid)
    if last and now_utc - last < timedelta(hours=STALE_HOURS):
        return
    since = last or datetime(2000, 1, 1, tzinfo=timezone.utc)
    sent = (
        db.table("notification_log").select("created_at").eq("athlete_id", aid).eq("kind", "sync")
        .gte("created_at", since.isoformat()).execute().data
    ) or []
    if not sync_alert_due([t for t in (_parse_dt(r.get("created_at")) for r in sent) if t], now_utc):
        return
    if not cn.claim(aid, "sync", local_now.date().isoformat()):
        return
    names = " and ".join(PROVIDER_NAMES[p] for p in providers)
    send_push_to_athlete(
        athlete_id=aid,
        title=f"{names} stopped sending data",
        body=f"Nothing new for {STALE_HOURS // 24} days. Open Connected apps to reconnect.",
        db=db,
        data={"url": "/profile/connections", "type": "sync"},
    )
