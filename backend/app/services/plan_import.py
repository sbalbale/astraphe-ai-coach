"""Import a training plan (document or photo in the chat) into the calendar in one step.

The chat model only decides to import and passes the date range and the athlete's rules. This
module sends the plan to a stronger model in ONE structured-output request, checks the result
in code (dates and weekdays, range, duplicates, a zone on every block), then replaces the
not-done sessions in the covered dates and saves the new ones.

Prod, Nov 2026: importing two months through dozens of schedule_workouts calls on a lite model
dropped days, shifted dates, mis-built intervals and lost zones, and every fix in chat broke
something else. One request also matters for quota: the stronger models allow ~20 requests a
day per project, shared by every athlete.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from app.config import settings
from app.services import gemini_quota
from app.services.coach_tools import FOCUS_ZONES, handle_schedule_workout

logger = logging.getLogger(__name__)

IMPORT_MAX_DAYS = 62
_DOC_CHARS = 60000
_RECENT_ATHLETE_MESSAGES = 8
_SPORTS = ("run", "bike", "swim", "row", "strength", "mobility", "other")
_SPORT_ALIASES = {
    "cycling": "bike", "ride": "bike", "biking": "bike", "trainer": "bike", "running": "run",
    "rowing": "row", "erg": "row", "gym": "strength", "weights": "strength", "lifting": "strength",
    "yoga": "mobility", "stretching": "mobility", "swimming": "swim",
}
# Zone used for a block the model left without one, from the session's focus.
_FOCUS_TO_ZONE = {"Recovery": 1, "Endurance": 2, "Tempo": 3, "Threshold": 4, "VO2Max": 5, "Anaerobic": 5}
_ZONE_TO_FOCUS = {1: "Recovery", 2: "Endurance", 3: "Tempo", 4: "Threshold", 5: "VO2Max"}
# One entry holding two sessions: "AM - Cat 1 cross-train PM - Team ST".
_MERGED_AM_PM = re.compile(r"(?-i:AM)\s*[-:\u2013\u2014].+(?-i:PM)\s*[-:\u2013\u2014]")
# Titles that are gym sessions whatever sport the reader picked ("Team ST", "S&C", "Lift").
_STRENGTH_TITLE = re.compile(r"\b(?:(?-i:ST)|S ?& ?C|strength|lift(?:ing)?|gym|weights)\b", re.IGNORECASE)

_client_lock = threading.Lock()
_client: Any = None

# Daily quota: a model that answered "per day" 429 is skipped until Google's reset (midnight
# Pacific). Per athlete: imports today, so one athlete can't spend the shared daily budget.
_exhausted_until: dict[str, datetime] = {}
_athlete_imports: dict[tuple[str, str], int] = {}
_state_lock = threading.Lock()


def _import_client() -> Any:
    """Own client: a full plan can take minutes to write, past the chat client's timeout."""
    global _client
    with _client_lock:
        if _client is None:
            _client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(timeout=int(settings.PLAN_IMPORT_TIMEOUT_SEC) * 1000),
            )
        return _client


def import_models() -> list[str]:
    models = [m.strip() for m in (settings.GEMINI_IMPORT_MODELS or "").split(",") if m.strip()]
    chat = (settings.GEMINI_MODEL or "").strip()
    if settings.PLAN_IMPORT_CHAT_FALLBACK and chat and chat not in models:
        models.append(chat)  # last resort: still one request, on the chat model's own quota
    return models


def _next_pacific_midnight(now: datetime) -> datetime:
    pt = now.astimezone(ZoneInfo("America/Los_Angeles"))
    nxt = datetime.combine(pt.date() + timedelta(days=1), datetime.min.time(), tzinfo=pt.tzinfo)
    return nxt.astimezone(timezone.utc)


def _is_exhausted(model: str, now: datetime) -> bool:
    with _state_lock:
        until = _exhausted_until.get(model)
        return bool(until and now < until)


def _mark_exhausted(model: str, now: datetime) -> None:
    with _state_lock:
        _exhausted_until[model] = _next_pacific_midnight(now)


def _athlete_quota_left(athlete_id: str, today: str) -> int:
    with _state_lock:
        return int(settings.PLAN_IMPORTS_PER_DAY) - _athlete_imports.get((athlete_id, today), 0)


def _count_athlete_import(athlete_id: str, today: str) -> None:
    with _state_lock:
        for k in [k for k in _athlete_imports if k[1] != today]:
            del _athlete_imports[k]
        _athlete_imports[(athlete_id, today)] = _athlete_imports.get((athlete_id, today), 0) + 1


# --- response schema ---------------------------------------------------------------------

_BLOCK = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "name": types.Schema(type=types.Type.STRING, description="Warmup, Main set, 8 x 1:30, Cooldown, ..."),
        "minutes": types.Schema(
            type=types.Type.NUMBER,
            description="Length of ONE work rep (or of the whole block when repeat is 1). Decimals allowed: 1:30 = 1.5.",
        ),
        "zone": types.Schema(type=types.Type.INTEGER, description="Intensity zone 1-5. Always set."),
        "repeat": types.Schema(type=types.Type.INTEGER, description="Number of reps, 1 if not an interval set."),
        "recovery_minutes": types.Schema(type=types.Type.NUMBER, description="Rest between reps (0 if none)."),
        "recovery_zone": types.Schema(type=types.Type.INTEGER, description="Zone of the rest between reps, usually 1."),
        "target": types.Schema(type=types.Type.STRING, description="Target as written, e.g. '85-90% FTP', '180-195 W', 'rate 28'."),
    },
    required=["name", "minutes", "zone", "repeat"],
)

_SESSION = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "date": types.Schema(type=types.Type.STRING, description="YYYY-MM-DD, from the calendar list."),
        "weekday": types.Schema(type=types.Type.STRING, description="Weekday of that date, from the calendar list."),
        "title": types.Schema(type=types.Type.STRING, description="The plan's own name for the session."),
        "sport": types.Schema(type=types.Type.STRING, enum=list(_SPORTS)),
        "duration_minutes": types.Schema(type=types.Type.NUMBER),
        "focus_zone": types.Schema(type=types.Type.STRING, enum=list(FOCUS_ZONES)),
        "notes": types.Schema(type=types.Type.STRING, description="One or two plain sentences (no tables, no markdown)."),
        "blocks": types.Schema(type=types.Type.ARRAY, items=_BLOCK, description="Empty for strength and mobility."),
    },
    required=["date", "weekday", "title", "sport", "duration_minutes", "focus_zone", "blocks"],
)

RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "sessions": types.Schema(type=types.Type.ARRAY, items=_SESSION),
        "unclear": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
            description="Anything in the plan you could not place or had to guess, one short line each.",
        ),
    },
    required=["sessions"],
)


# --- sources -----------------------------------------------------------------------------

def plan_sources(history: list[dict], current_message: str, document_name: str | None) -> tuple[str, list[str]]:
    """Plan text from documents attached in this conversation (newest first, or the named one)
    plus the photo URLs of the newest user message that has photos."""
    want = (document_name or "").strip().lower()
    texts: list[str] = []
    budget = _DOC_CHARS
    image_urls: list[str] = []
    for row in reversed(history):
        if row.get("role") != "user":
            continue
        if not image_urls and row.get("image_urls"):
            image_urls = list(row["image_urls"])
        for d in row.get("attachments") or []:
            if not isinstance(d, dict) or budget <= 0:
                continue
            name = str(d.get("name") or "document")
            if want and want not in name.lower():
                continue
            text = str(d.get("content") or "")[:budget]
            if text.strip():
                budget -= len(text)
                texts.append(f"[DOCUMENT: {name}]\n{text}")
    # The message being answered can carry its documents inline (see routers/coach.py).
    if not texts and "[ATTACHED DOCUMENT:" in (current_message or ""):
        texts.append(current_message[:_DOC_CHARS])
    return "\n\n".join(texts), image_urls


def _athlete_said(history: list[dict], current_message: str) -> str:
    said = [str(r.get("content") or "")[:500] for r in history if r.get("role") == "user"]
    said = [s for s in said if s.strip()][-_RECENT_ATHLETE_MESSAGES:]
    tail = (current_message or "").split("[ATHLETE MESSAGE]")[-1].strip()[:500]
    if tail and (not said or said[-1] != tail):
        said.append(tail)
    return "\n".join(f"- {s}" for s in said)


def build_prompt(start: date, end: date, rules: str, athlete_said: str, plan_text: str) -> str:
    days = "\n".join(
        f"{(start + timedelta(days=i)).isoformat()} {(start + timedelta(days=i)).strftime('%A')}"
        for i in range((end - start).days + 1)
    )
    return f"""You turn an athlete's training plan into calendar sessions.

Dates to fill, with their weekdays (use exactly these; never invent another date):
{days}

The athlete's rules (these override the plan's wording):
{rules.strip() or "(none given)"}

What the athlete said in this chat (newest last):
{athlete_said or "(nothing)"}

Instructions:
- One entry per session. Two sessions on a day (AM and PM) are two entries.
- Cover every listed date the plan covers. Leave out rest / open / off days with nothing prescribed.
- Take each session's weekday from the plan's own layout (its "week of" rows and weekday columns),
  then give the date that has that weekday in the list above.
- Keep the plan's names as titles. sport is one of {", ".join(_SPORTS)}; apply the athlete's rules
  (e.g. "cross-train = cycling on the trainer" means sport bike).
- duration_minutes is the whole session. Blocks must add up to it.
- Every block has a zone 1-5 (1 recovery, 2 endurance, 3 tempo/sweet spot low, 4 threshold/sweet
  spot high, 5 VO2/speed). Use the plan's targets to choose.
- Intervals are ONE block: "8 x 1:30 hard, 1:00 easy" = minutes 1.5, repeat 8, zone 5,
  recovery_minutes 1, recovery_zone 1. Add warmup and cooldown blocks when the plan has them or the
  session is longer than the main set.
- Strength and mobility: sport strength / mobility, focus_zone Recovery, no blocks. "ST", "S&C",
  lift and gym sessions are strength.
- notes: one or two plain sentences, no tables or markdown.
- Put anything you could not place, or had to guess, in "unclear".

The plan:
{plan_text}
"""


# --- model call --------------------------------------------------------------------------

def _is_daily_quota(err: str) -> bool:
    e = err.lower()
    return ("429" in e or "resource_exhausted" in e or "quota" in e) and ("per day" in e or "perday" in e or "daily" in e)


def _is_busy(err: str) -> bool:
    return "503" in err or "UNAVAILABLE" in err or "high demand" in err


# Waits before the 2nd and 3rd try of a model answering 503 "high demand".
_BUSY_RETRY_SEC = (5.0, 15.0)


def call_import_model(contents: list[Any], now: datetime | None = None) -> tuple[dict | None, str | None, list[str]]:
    """One request, trying each import model in turn. Returns (parsed, model, errors).

    A model that is busy (503) gets one more try after a few seconds; quota errors and
    timeouts go straight to the next model."""
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    strong = {m.strip() for m in (settings.GEMINI_IMPORT_MODELS or "").split(",") if m.strip()}
    level = (settings.PLAN_IMPORT_THINKING_LEVEL or "").strip().upper()
    for model in import_models():
        if _is_exhausted(model, now):
            errors.append(f"{model}: daily limit reached")
            continue
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            # Full thinking on a two-month plan ran past the deadline (504); low is ~1 min.
            thinking_config=types.ThinkingConfig(thinking_level=level) if (level and model in strong) else None,
        )
        resp = None
        for attempt in range(len(_BUSY_RETRY_SEC) + 1):
            try:
                gemini_quota.wait_for_slot(model, max_wait_sec=30.0)
                resp = _import_client().models.generate_content(model=model, contents=contents, config=config)
                break
            except Exception as e:
                msg = str(e)
                if _is_daily_quota(msg):
                    _mark_exhausted(model, now)
                logger.warning("[plan_import] %s failed (attempt %s): %s", model, attempt + 1, msg[:300])
                if attempt < len(_BUSY_RETRY_SEC) and _is_busy(msg):
                    time.sleep(_BUSY_RETRY_SEC[attempt])
                    continue
                errors.append(f"{model}: {msg[:160]}")
                break
        if resp is None:
            continue
        parsed = getattr(resp, "parsed", None)
        if not isinstance(parsed, dict):
            try:
                parsed = json.loads(resp.text or "")
            except (ValueError, TypeError):
                parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("sessions"), list):
            return parsed, model, errors
        errors.append(f"{model}: unreadable response")
    return None, None, errors


# --- checks ------------------------------------------------------------------------------

def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f > 0 else 0.0


def _zone(v: Any, default: int) -> tuple[int, bool]:
    try:
        z = int(v)
    except (TypeError, ValueError):
        return default, True
    if 1 <= z <= 5:
        return z, False
    return default, True


def _sport(v: Any) -> str:
    s = str(v or "other").strip().lower()
    s = _SPORT_ALIASES.get(s, s)
    return s if s in _SPORTS else "other"


def _fmt_min(m: float) -> str:
    whole = int(m)
    sec = int(round((m - whole) * 60))
    if sec == 60:
        whole, sec = whole + 1, 0
    return f"{whole} min" if not sec else f"{whole}:{sec:02d}"


def build_structure(blocks: list[dict], focus_zone: str) -> tuple[list[dict], float, int]:
    """Blocks → the app's flat structure (reps expanded to Work / Recovery). Returns
    (structure, total minutes, number of zones filled in because the model left them out)."""
    default = _FOCUS_TO_ZONE.get(focus_zone, 2)
    out: list[dict] = []
    total = 0.0
    filled = 0
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        mins = _num(b.get("minutes"))
        if mins <= 0:
            continue
        z, missing = _zone(b.get("zone"), default)
        filled += int(missing)
        name = str(b.get("name") or "Step").strip()[:60] or "Step"
        target = str(b.get("target") or "").strip()[:80]
        try:
            reps = max(1, min(int(b.get("repeat") or 1), 50))
        except (TypeError, ValueError):
            reps = 1
        rest = _num(b.get("recovery_minutes"))
        rz, _ = _zone(b.get("recovery_zone"), 1)
        if reps == 1:
            out.append({"name": name, "duration_minutes": mins, "target_hr_zone": z, "description": target})
            total += mins
            continue
        for r in range(reps):
            out.append({"name": f"Work {r + 1}/{reps}", "duration_minutes": mins, "target_hr_zone": z, "description": target})
            total += mins
            if rest > 0 and r < reps - 1:
                out.append({"name": f"Recovery {r + 1}/{reps - 1}", "duration_minutes": rest, "target_hr_zone": rz, "description": ""})
                total += rest
    return out, total, filled


def notes_markdown(notes: str, blocks: list[dict], focus_zone: str) -> str:
    """Plain notes, then a real (multi-line) prescription table built from the blocks."""
    rows = []
    default = _FOCUS_TO_ZONE.get(focus_zone, 2)
    for b in blocks or []:
        if not isinstance(b, dict) or _num(b.get("minutes")) <= 0:
            continue
        z, _ = _zone(b.get("zone"), default)
        mins = _num(b.get("minutes"))
        try:
            reps = max(1, int(b.get("repeat") or 1))
        except (TypeError, ValueError):
            reps = 1
        dur = _fmt_min(mins) if reps == 1 else f"{reps} x {_fmt_min(mins)}"
        rest = _num(b.get("recovery_minutes"))
        if reps > 1 and rest:
            dur += f" / {_fmt_min(rest)} easy"
        cell = lambda s: str(s or "").replace("|", "/").replace("\n", " ").strip()  # noqa: E731
        rows.append(f"| {cell(b.get('name'))} | {dur} | Z{z} | {cell(b.get('target'))} |")
    text = " ".join(str(notes or "").replace("|", "/").split())[:400]
    if not rows:
        return text
    table = "| Phase | Duration | Intensity | Target |\n| :--- | :---: | :---: | :--- |\n" + "\n".join(rows)
    return f"{text}\n\n{table}" if text else table


def check_sessions(raw: list[Any], start: date, end: date) -> tuple[list[dict], list[dict], int]:
    """Sessions that pass the checks (ready for handle_schedule_workout), the ones that don't
    (with a reason), and how many block zones had to be filled in."""
    ok: list[dict] = []
    skipped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    zones_filled = 0
    for s in raw:
        if not isinstance(s, dict):
            continue
        title = " ".join(str(s.get("title") or "").split())[:120]
        d_raw = str(s.get("date") or "")[:10]
        try:
            d = date.fromisoformat(d_raw)
        except ValueError:
            skipped.append({"date": d_raw, "title": title, "reason": "no valid date"})
            continue
        if not (start <= d <= end):
            skipped.append({"date": d_raw, "title": title, "reason": "outside the import range"})
            continue
        given = str(s.get("weekday") or "").strip().lower()
        actual = d.strftime("%A")
        if given and not actual.lower().startswith(given[:3]):
            skipped.append({"date": d_raw, "title": title, "reason": f"{d_raw} is a {actual}, but the plan put it on {s.get('weekday')}"})
            continue
        key = (d_raw, title.lower())
        if not title or key in seen:
            if title:
                skipped.append({"date": d_raw, "title": title, "reason": "listed twice"})
            continue
        seen.add(key)
        sport = _sport(s.get("sport"))
        if sport not in ("strength", "mobility") and _STRENGTH_TITLE.search(title):
            sport = "strength"
        focus = str(s.get("focus_zone") or "Endurance")
        if focus not in FOCUS_ZONES:
            focus = "Endurance"
        blocks = s.get("blocks") if isinstance(s.get("blocks"), list) else []
        duration = _num(s.get("duration_minutes"))
        structure: list[dict] = []
        if sport in ("strength", "mobility"):
            focus = "Recovery"
            blocks = []
        else:
            structure, total, filled = build_structure(blocks, focus)
            zones_filled += filled
            if structure:
                if duration <= 0:
                    duration = total
                hardest = max(int(b["target_hr_zone"]) for b in structure)
                if focus == "Endurance" and hardest >= 4:
                    focus = _ZONE_TO_FOCUS[hardest]
        if duration <= 0:
            skipped.append({"date": d_raw, "title": title, "reason": "no duration"})
            continue
        ok.append({
            "date": d_raw,
            "weekday": actual,
            "title": title,
            "sport": sport,
            "duration_minutes": int(round(min(duration, 600))),
            "focus_zone": focus,
            "structure": structure,
            "markdown_notes": notes_markdown(str(s.get("notes") or ""), blocks, focus),
        })
    ok.sort(key=lambda x: (x["date"], x["title"]))
    return ok, skipped, zones_filled


def by_weekday(sessions: list[dict]) -> dict[str, str]:
    order = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    counts: dict[str, dict[str, int]] = {d: {} for d in order}
    for s in sessions:
        c = counts[s["weekday"]]
        c[s["title"]] = c.get(s["title"], 0) + 1
    return {d: (", ".join(f"{t} x{n}" for t, n in c.items()) or "nothing") for d, c in counts.items()}


# --- the tool ----------------------------------------------------------------------------

def run_import(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Any,
    history: list[dict],
    current_message: str,
    load_images: Callable[[list[str]], list[types.Part]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    try:
        start = date.fromisoformat(str(args.get("start_date"))[:10])
        end = date.fromisoformat(str(args.get("end_date"))[:10])
    except ValueError:
        return {"error": "start_date and end_date must be YYYY-MM-DD"}
    if end < start:
        return {"error": "end_date is before start_date"}
    if (end - start).days + 1 > IMPORT_MAX_DAYS:
        return {"error": f"At most {IMPORT_MAX_DAYS} days per import; import the rest with a second call."}

    plan_text, image_urls = plan_sources(history, current_message, args.get("document_name"))
    images = load_images(image_urls) if (load_images and image_urls) else []
    if not plan_text.strip() and not images:
        return {"error": "no_plan_attached", "message": "No plan document or photo in this conversation. Ask the athlete to attach it."}

    today = now.date().isoformat()
    if _athlete_quota_left(athlete_id, today) <= 0:
        return {
            "error": "daily_import_limit",
            "message": f"The athlete has used today's {settings.PLAN_IMPORTS_PER_DAY} plan imports. They reset tomorrow; small edits still work now.",
        }

    prompt = build_prompt(start, end, str(args.get("rules") or ""), _athlete_said(history, current_message), plan_text or "(see the photos)")
    contents: list[Any] = [types.Content(role="user", parts=[*images, types.Part.from_text(text=prompt)])]
    parsed, model, errors = call_import_model(contents, now=now)
    if parsed is None:
        return {
            "error": "plan_reader_unavailable",
            "message": (
                "The plan reader is busy or at its limit right now, so nothing was changed. Tell the "
                "athlete to send the same message again in a few minutes; this didn't use one of their imports."
            ),
            "details": errors[:4],
        }
    _count_athlete_import(athlete_id, today)

    sessions, skipped, zones_filled = check_sessions(parsed.get("sessions") or [], start, end)
    unclear = [str(u)[:200] for u in (parsed.get("unclear") or []) if str(u).strip()][:10]
    merged = [s for s in sessions if _MERGED_AM_PM.search(s["title"])]
    if merged:
        unclear.insert(0, f"{len(merged)} sessions still combine an AM and a PM session in one entry (e.g. {merged[0]['date']}: {merged[0]['title']}).")
    if skipped:
        reasons: dict[str, int] = {}
        for k in skipped:
            r = k["reason"] if "is a " not in k["reason"] else "date/weekday mismatch"
            reasons[r] = reasons.get(r, 0) + 1
        logger.info("[plan_import] skipped by reason: %s; first: %s", reasons, skipped[:3])
    if not sessions:
        return {"error": "nothing_to_import", "message": "No sessions could be read for those dates. Nothing was changed.", "skipped": skipped[:10], "unclear": unclear}

    # Replace only the dates the import covers (first to last session), and only sessions
    # that aren't done: a plan that only covers November never touches December.
    first, last = sessions[0]["date"], sessions[-1]["date"]
    deleted = db.table("training_plans").delete().eq("athlete_id", athlete_id).in_(
        "status", ["planned", "modified"]
    ).gte("planned_date", first).lte("planned_date", last).execute()
    replaced = len(getattr(deleted, "data", None) or [])

    saved: list[dict] = []
    for s in sessions:
        res = handle_schedule_workout(dict(s), athlete_id=athlete_id, db=db)
        if res.get("error"):
            skipped.append({"date": s["date"], "title": s["title"], "reason": str(res["error"])[:160]})
        elif res.get("skipped") == "duplicate":
            skipped.append({"date": s["date"], "title": s["title"], "reason": "already done that day"})
        else:
            saved.append(s)

    covered = {s["date"] for s in saved}
    empty = [
        (start + timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).isoformat() not in covered
    ]
    logger.info("[plan_import] athlete=%s model=%s saved=%s skipped=%s replaced=%s", athlete_id, model, len(saved), len(skipped), replaced)
    return {
        "status": "imported",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "saved_count": len(saved),
        "replaced_planned_sessions": replaced,
        "by_weekday": by_weekday(saved),
        "days_without_sessions": len(empty),
        "skipped": skipped[:20],
        "unclear": unclear,
        "zones_filled_in": zones_filled,
        "note": (
            "Saved. Tell the athlete what is now on the calendar from by_weekday and CALENDAR NOW, "
            "and list anything skipped or unclear. Don't ask for confirmation; it is already saved."
        ),
    }
