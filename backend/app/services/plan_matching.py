"""Linking recorded workouts to planned sessions (training_plans).

- Auto-match: when a workout is saved, it completes the planned session on the same local
  day with the same sport and a similar duration (50–150% of planned; closest wins). One
  workout completes at most one session. A workout the athlete dismissed for a session
  ("Not this one", or unlinking an auto-match) is never auto-matched to it again.
- Manual: the athlete can link any workout within a couple of days (any sport, with a
  warning in the UI), move a link from another session, unlink, or mark done without one.

Session states: done + completed_workout_id = linked; done without it = done by hand;
planned / modified = not done.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services.time_utils import fetch_athlete_timezone_offset_min

logger = logging.getLogger(__name__)

AUTO_MIN_RATIO = 0.5
AUTO_MAX_RATIO = 1.5
CANDIDATE_DAYS = 2
NOT_DONE = ("planned", "modified")

_PLAN_COLUMNS = (
    "id,planned_date,sport,title,duration_min,target_tss,status,completed_workout_id,"
    "link_source,dismissed_workout_ids,primary_zone"
)
_WORKOUT_COLUMNS = "id,sport,title,started_at,duration_seconds,tss,source,primary_source"

# Workouts and plans share these sport words; a few provider words are folded in.
_SPORT_ALIASES = {
    "cycling": "bike",
    "ride": "bike",
    "virtualride": "bike",
    "running": "run",
    "rowing": "row",
    "gym": "strength",
    "weights": "strength",
    "yoga": "mobility",
    "swimming": "swim",
}


def normalize_sport(sport: Any) -> str:
    s = str(sport or "other").strip().lower()
    return _SPORT_ALIASES.get(s, s)


def _parse_ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_day(started_at: Any, offset_min: int) -> Optional[date]:
    dt = _parse_ts(started_at)
    if dt is None:
        return None
    return (dt.astimezone(timezone.utc) + timedelta(minutes=offset_min or 0)).date()


def _plan_date(plan: dict) -> Optional[date]:
    try:
        return date.fromisoformat(str(plan.get("planned_date"))[:10])
    except ValueError:
        return None


def fit(plan: dict, workout: dict, offset_min: int) -> dict:
    """How well a recorded workout fits a planned session (lower score = better)."""
    w_day = local_day(workout.get("started_at"), offset_min)
    p_day = _plan_date(plan)
    day_offset = (w_day - p_day).days if (w_day and p_day) else 99
    sport_ok = normalize_sport(plan.get("sport")) == normalize_sport(workout.get("sport"))
    planned_min = float(plan.get("duration_min") or 0)
    actual_min = float(workout.get("duration_seconds") or 0) / 60.0
    ratio = (actual_min / planned_min) if planned_min > 0 else None
    duration_ok = ratio is None or AUTO_MIN_RATIO <= ratio <= AUTO_MAX_RATIO
    score = abs(day_offset) * 10 + (0 if sport_ok else 5) + (abs(1 - ratio) * 4 if ratio is not None else 1)
    if day_offset == 0:
        when = "same day"
    else:
        n = abs(day_offset)
        when = f"{n} day{'s' if n > 1 else ''} {'late' if day_offset > 0 else 'early'}"
    if not sport_ok:
        reason = "different sport"
    elif ratio is not None and abs(ratio - 1) <= 0.15:
        reason = f"{when} · similar duration"
    elif ratio is not None:
        reason = f"{when} · {'longer' if ratio > 1 else 'shorter'} than planned"
    else:
        reason = when
    return {
        "day_offset": day_offset,
        "sport_ok": sport_ok,
        "duration_ratio": round(ratio, 2) if ratio is not None else None,
        "duration_ok": duration_ok,
        "auto_ok": day_offset == 0 and sport_ok and duration_ok,
        "score": round(score, 2),
        "reason": reason,
    }


def workout_summary(w: dict) -> dict:
    return {
        "id": w.get("id"),
        "title": w.get("title") or "Workout",
        "sport": normalize_sport(w.get("sport")),
        "started_at": w.get("started_at"),
        "duration_seconds": int(w.get("duration_seconds") or 0),
        "tss": round(float(w["tss"])) if w.get("tss") is not None else None,
    }


def plan_summary(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "date": str(p.get("planned_date"))[:10],
        "title": p.get("title") or "",
        "sport": normalize_sport(p.get("sport")),
        "duration_minutes": int(p.get("duration_min") or 0),
        "projected_tss": int(p.get("target_tss") or 0),
        "status": p.get("status"),
        "completed": p.get("status") == "done",
        "link_source": p.get("link_source"),
    }


# --- queries -------------------------------------------------------------------------------

def _plan(db: Any, athlete_id: str, plan_id: str) -> Optional[dict]:
    res = (
        db.table("training_plans").select(_PLAN_COLUMNS).eq("id", plan_id).eq("athlete_id", athlete_id).limit(1).execute()
    )
    return (res.data or [None])[0]


def _workout(db: Any, athlete_id: str, workout_id: str) -> Optional[dict]:
    res = db.table("workouts").select(_WORKOUT_COLUMNS).eq("id", workout_id).eq("athlete_id", athlete_id).limit(1).execute()
    return (res.data or [None])[0]


def _workouts_between(db: Any, athlete_id: str, start: date, end: date, offset_min: int) -> list[dict]:
    """Workouts whose local day is in [start, end] (queried with a UTC margin, then filtered)."""
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) - timedelta(days=1)
    hi = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=2)
    res = (
        db.table("workouts")
        .select(_WORKOUT_COLUMNS)
        .eq("athlete_id", athlete_id)
        .gte("started_at", lo.isoformat())
        .lt("started_at", hi.isoformat())
        .order("started_at")
        .limit(200)
        .execute()
    )
    out = []
    for w in res.data or []:
        d = local_day(w.get("started_at"), offset_min)
        if d and start <= d <= end:
            out.append(w)
    return out


def _plans_between(db: Any, athlete_id: str, start: date, end: date) -> list[dict]:
    res = (
        db.table("training_plans")
        .select(_PLAN_COLUMNS)
        .eq("athlete_id", athlete_id)
        .gte("planned_date", start.isoformat())
        .lte("planned_date", end.isoformat())
        .order("planned_date")
        .limit(200)
        .execute()
    )
    return res.data or []


def _linked_plan_for_workout(db: Any, athlete_id: str, workout_id: str) -> Optional[dict]:
    res = (
        db.table("training_plans")
        .select(_PLAN_COLUMNS)
        .eq("athlete_id", athlete_id)
        .eq("completed_workout_id", workout_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def linked_workouts_by_id(db: Any, athlete_id: str, workout_ids: list[str]) -> dict[str, dict]:
    ids = [i for i in dict.fromkeys(workout_ids) if i]
    if not ids:
        return {}
    res = db.table("workouts").select(_WORKOUT_COLUMNS).eq("athlete_id", athlete_id).in_("id", ids).execute()
    return {w["id"]: workout_summary(w) for w in (res.data or [])}


# --- candidates --------------------------------------------------------------------------

def candidates_for_plan(db: Any, athlete_id: str, plan_id: str, days: int = CANDIDATE_DAYS) -> dict:
    plan = _plan(db, athlete_id, plan_id)
    if not plan:
        raise LookupError("plan not found")
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    p_day = _plan_date(plan) or date.today()
    workouts = _workouts_between(db, athlete_id, p_day - timedelta(days=days), p_day + timedelta(days=days), offset)
    linked = (
        db.table("training_plans")
        .select("id,title,planned_date,completed_workout_id")
        .eq("athlete_id", athlete_id)
        .in_("completed_workout_id", [w["id"] for w in workouts] or ["00000000-0000-0000-0000-000000000000"])
        .execute()
    ).data or []
    by_workout = {r["completed_workout_id"]: r for r in linked}
    dismissed = set(plan.get("dismissed_workout_ids") or [])
    rows = []
    for w in workouts:
        f = fit(plan, w, offset)
        other = by_workout.get(w["id"])
        rows.append(
            {
                **workout_summary(w),
                "fit": f,
                "dismissed": w["id"] in dismissed,
                "linked_here": bool(other and other["id"] == plan_id),
                "linked_to": (
                    {"id": other["id"], "title": other.get("title"), "date": str(other.get("planned_date"))[:10]}
                    if other and other["id"] != plan_id
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (not r["fit"]["sport_ok"], r["fit"]["score"]))
    return {"plan": plan_summary(plan), "candidates": rows, "suggestion": _suggestion(plan, rows)}


def _suggestion(plan: dict, rows: list[dict]) -> Optional[dict]:
    """The one-tap "Looks like a match" for a session that isn't done: same sport, within
    the window, not dismissed, not linked elsewhere. Includes ones auto-match skipped (a day
    late, or synced after matching ran)."""
    if plan.get("status") not in NOT_DONE:
        return None
    for r in rows:
        if r["fit"]["sport_ok"] and not r["dismissed"] and not r["linked_to"] and not r["linked_here"]:
            return r
    return None


def candidates_for_workout(db: Any, athlete_id: str, workout_id: str, days: int = CANDIDATE_DAYS) -> dict:
    w = _workout(db, athlete_id, workout_id)
    if not w:
        raise LookupError("workout not found")
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    w_day = local_day(w.get("started_at"), offset) or date.today()
    plans = _plans_between(db, athlete_id, w_day - timedelta(days=days), w_day + timedelta(days=days))
    linked = next((p for p in plans if p.get("completed_workout_id") == workout_id), None) or _linked_plan_for_workout(
        db, athlete_id, workout_id
    )
    rows = []
    for p in plans:
        f = fit(p, w, offset)
        rows.append(
            {
                **plan_summary(p),
                "fit": f,
                "linked_here": p.get("completed_workout_id") == workout_id,
                "has_other_workout": bool(p.get("completed_workout_id")) and p.get("completed_workout_id") != workout_id,
                "dismissed": workout_id in set(p.get("dismissed_workout_ids") or []),
            }
        )
    rows.sort(key=lambda r: (not r["fit"]["sport_ok"], r["fit"]["score"]))
    suggestion = None
    if not linked:
        suggestion = next(
            (
                r
                for r in rows
                if r["fit"]["sport_ok"] and r["status"] in NOT_DONE and not r["dismissed"] and not r["has_other_workout"]
            ),
            None,
        )
    return {
        "workout": workout_summary(w),
        "linked": plan_summary(linked) if linked else None,
        "candidates": rows,
        "suggestion": suggestion,
    }


# --- link / unlink -----------------------------------------------------------------------

class LinkConflict(Exception):
    """The workout already completes another session (pass move=True to move the link)."""

    def __init__(self, other: dict):
        super().__init__("workout already linked")
        self.other = other


def link(db: Any, athlete_id: str, plan_id: str, workout_id: str, *, source: str = "manual", move: bool = False) -> dict:
    plan = _plan(db, athlete_id, plan_id)
    if not plan:
        raise LookupError("plan not found")
    if not _workout(db, athlete_id, workout_id):
        raise LookupError("workout not found")
    if source == "auto" and plan.get("completed_workout_id"):
        raise LinkConflict(plan_summary(plan))  # already completed by another recording
    other = _linked_plan_for_workout(db, athlete_id, workout_id)
    moved_from: Optional[dict] = None
    if other and other["id"] != plan_id:
        if not move:
            raise LinkConflict(plan_summary(other))
        _clear_link(db, athlete_id, other["id"])
        moved_from = other
    dismissed = [d for d in (plan.get("dismissed_workout_ids") or []) if d != workout_id]
    q = (
        db.table("training_plans")
        .update({"status": "done", "completed_workout_id": workout_id, "link_source": source, "dismissed_workout_ids": dismissed})
        .eq("id", plan_id)
        .eq("athlete_id", athlete_id)
    )
    if source == "auto":
        # Two replicas matching at once: only the first fills an empty session.
        q = q.is_("completed_workout_id", "null")
    try:
        res = q.execute()
    except Exception as e:
        if moved_from:  # put the link we just cleared back
            _restore_link(db, athlete_id, moved_from)
        if _is_unique_violation(e):  # another request linked this workout in between
            current = _linked_plan_for_workout(db, athlete_id, workout_id)
            raise LinkConflict(plan_summary(current) if current else {}) from e
        raise
    if not res.data:
        if source == "auto":
            raise LinkConflict(plan_summary(plan))
        raise LookupError("plan not found")
    return res.data[0]


def _is_unique_violation(e: Exception) -> bool:
    text = f"{getattr(e, 'code', '')} {e}"
    return "23505" in text or "duplicate key" in text


def _restore_link(db: Any, athlete_id: str, prior: dict) -> None:
    """Best effort: relink a session whose link was cleared for a move that then failed."""
    try:
        db.table("training_plans").update({
            "status": prior.get("status") or "done",
            "completed_workout_id": prior.get("completed_workout_id"),
            "link_source": prior.get("link_source"),
        }).eq("id", prior["id"]).eq("athlete_id", athlete_id).execute()
    except Exception as e:
        logger.warning("[plan_matching] could not restore link plan=%s: %r", prior.get("id"), e)


def _clear_link(
    db: Any, athlete_id: str, plan_id: str, dismiss: Optional[str] = None, prior: Optional[list] = None, done: bool = False
) -> dict:
    update: dict[str, Any] = {"status": "done" if done else "planned", "completed_workout_id": None, "link_source": None}
    if dismiss:
        update["dismissed_workout_ids"] = list(dict.fromkeys([*(prior or []), dismiss]))
    res = db.table("training_plans").update(update).eq("id", plan_id).eq("athlete_id", athlete_id).execute()
    return (res.data or [{}])[0]


def unlink(db: Any, athlete_id: str, plan_id: str, *, dismiss: bool = True, done: bool = False) -> dict:
    """Back to not done. By default the workout is remembered as dismissed so auto-match won't
    relink it. Undo of a link passes `dismiss=False` (keep it suggestible) and `done=True` when
    the session was done by hand before the link."""
    plan = _plan(db, athlete_id, plan_id)
    if not plan:
        raise LookupError("plan not found")
    wid = plan.get("completed_workout_id") if dismiss else None
    return _clear_link(db, athlete_id, plan_id, dismiss=wid, prior=plan.get("dismissed_workout_ids"), done=done)


def dismiss(db: Any, athlete_id: str, plan_id: str, workout_id: str) -> dict:
    """"Not this one": never suggest or auto-match this workout for this session."""
    plan = _plan(db, athlete_id, plan_id)
    if not plan:
        raise LookupError("plan not found")
    ids = list(dict.fromkeys([*(plan.get("dismissed_workout_ids") or []), workout_id]))
    res = db.table("training_plans").update({"dismissed_workout_ids": ids}).eq("id", plan_id).eq("athlete_id", athlete_id).execute()
    return (res.data or [{}])[0]


# --- auto-match --------------------------------------------------------------------------

def auto_match_workout(db: Any, athlete_id: str, workout_id: str, offset_min: Optional[int] = None) -> Optional[str]:
    """Complete the best same-day session for a just-saved workout. Returns the plan id or None."""
    w = _workout(db, athlete_id, workout_id)
    if not w or _linked_plan_for_workout(db, athlete_id, workout_id):
        return None
    offset = fetch_athlete_timezone_offset_min(db, athlete_id) if offset_min is None else offset_min
    w_day = local_day(w.get("started_at"), offset)
    if not w_day:
        return None
    best: Optional[tuple[float, dict]] = None
    for p in _plans_between(db, athlete_id, w_day, w_day):
        if p.get("status") not in NOT_DONE or p.get("completed_workout_id"):
            continue
        if workout_id in set(p.get("dismissed_workout_ids") or []):
            continue
        f = fit(p, w, offset)
        if f["auto_ok"] and (best is None or f["score"] < best[0]):
            best = (f["score"], p)
    if not best:
        return None
    try:
        link(db, athlete_id, best[1]["id"], workout_id, source="auto")
    except Exception as e:  # e.g. a concurrent sync linked it first (unique index)
        logger.info("[plan_matching] auto-match skipped workout=%s: %r", workout_id, e)
        return None
    return best[1]["id"]


def auto_match_safe(db: Any, athlete_id: str, workout_id: str) -> Optional[str]:
    """auto_match_workout that never raises (called from the sync path)."""
    try:
        return auto_match_workout(db, athlete_id, workout_id)
    except Exception as e:
        logger.warning("[plan_matching] auto-match failed workout=%s: %r", workout_id, e)
        return None


def backfill(db: Any, athlete_id: str, since: date, until: Optional[date] = None) -> int:
    """Auto-match past workouts to not-done sessions (one-off after this feature ships)."""
    offset = fetch_athlete_timezone_offset_min(db, athlete_id)
    until = until or date.today()
    n = 0
    for w in _workouts_between(db, athlete_id, since, until, offset):
        if auto_match_workout(db, athlete_id, w["id"], offset_min=offset):
            n += 1
    return n
