from google.genai import types
from app.config import settings
from app.services import coach_tools
from app.services import gemini_quota
from app.services import plan_import
from app.services.coach_workout_data import pace_with_unit, recent_workouts_teaser
from app.services.algorithms import compute_z_score
from app.services.llm_provider import chat_uses_openai, client_for_chat_model, get_llm_client, is_chat_openai_model
from app.services.memory import (
    MEMORY_CONTEXT_RULE,
    memories_for_context,
    retrieve_relevant_memories,
    should_skip_rag_for_message,
)
import logging

logger = logging.getLogger(__name__)
from app.services.time_utils import (
    with_duration_text,
    coerce_timezone_offset_min,
    local_datetime_from_timezone_offset,
)
import asyncio
import json
import re
import time
from typing import Any, Callable

import httpx
import numpy as np
from supabase import Client
from datetime import date, timedelta


_client = get_llm_client()

def _should_fallback_chat_model(err_str: str) -> bool:
    """
    True when the primary chat model is likely temporarily overloaded/unavailable.
    We only use this to decide whether to try the configured fallback model.
    """
    s = (err_str or "").lower()
    return any(
        k in s
        for k in (
            "503",
            "unavailable",
            "high demand",
            "overloaded",
            "resource exhausted",
            "quota exceeded",
            # A hung request (httpx "The read operation timed out", Google's 504) is the
            # primary model being slow, so the fallback model is worth a try.
            "timed out",
            "timeout",
            "504",
            "deadline_exceeded",
        )
    )

def load_coach_instructions() -> str:
    prompt_file = settings.PROMPTS_DIR / settings.COACH_PROMPT_FILE
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are ASTRAPHE, an elite, data-driven performance coach."

def _safe_float(v: object) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _safe_int(v: object) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None

def _summarize_biometrics(db: Client, athlete_id: str, units: str = "metric") -> dict:
    """
    Pull a compact biometrics summary for LLM context.
    Keeps payload small: latest day + 7-day averages where possible.
    Converts units if necessary.
    """
    try:
        bio_res = (
            db.table("biometrics")
            .select(
                "date,hrv_rmssd,resting_hr,sleep_duration_min,sleep_score,recovery_score,readiness_score,"
                "strain_score,spo2_pct,skin_temp"
            )
            .eq("athlete_id", athlete_id)
            .order("date", desc=True)
            .limit(14)
            .execute()
        )
        rows = bio_res.data or []
    except Exception as e:
        return {"error": f"biometrics_query_failed: {str(e)}"}

    if not rows:
        return {"available": False}

    def _convert_temp(c: float | None) -> float | None:
        if c is None: return None
        if units == "imperial":
            return round((c * 9/5) + 32, 2)
        return round(c, 2)

    latest = rows[0]
    # Compute 7d averages (use available values only)
    def avg(key: str) -> float | None:
        vals: list[float] = []
        for r in rows[:7]:
            v = _safe_float(r.get(key))
            if v is not None:
                vals.append(v)
        return (sum(vals) / len(vals)) if vals else None

    summary = {
        "available": True,
        "units": "Fahrenheit (°F)" if units == "imperial" else "Celsius (°C)",
        "latest": {
            "date": latest.get("date"),
            "hrv_rmssd": _safe_float(latest.get("hrv_rmssd")),
            "resting_hr": _safe_int(latest.get("resting_hr")),
            "sleep_duration_min": _safe_int(latest.get("sleep_duration_min")),
            "sleep_score": _safe_int(latest.get("sleep_score")),
            "recovery_score": _safe_int(latest.get("recovery_score")),
            "readiness_score": _safe_int(latest.get("readiness_score")),
            "strain_score": _safe_int(latest.get("strain_score")),
            "spo2_pct": _safe_float(latest.get("spo2_pct")),
            "skin_temp": _convert_temp(_safe_float(latest.get("skin_temp"))),
        },
        "avg_7d": {
            "hrv_rmssd": avg("hrv_rmssd"),
            "resting_hr": avg("resting_hr"),
            "sleep_duration_min": avg("sleep_duration_min"),
            "sleep_score": avg("sleep_score"),
            "recovery_score": avg("recovery_score"),
            "readiness_score": avg("readiness_score"),
            "strain_score": avg("strain_score"),
            "spo2_pct": avg("spo2_pct"),
            "skin_temp": _convert_temp(avg("skin_temp")),
        },
    }

    # Add simple deltas vs 7d avg for the most important signals
    for k in ("hrv_rmssd", "resting_hr", "sleep_duration_min", "sleep_score", "recovery_score", "spo2_pct", "skin_temp"):
        lv = _safe_float(summary["latest"].get(k))
        av = _safe_float(summary["avg_7d"].get(k))
        if lv is not None and av is not None:
            summary["delta_vs_7d_avg"] = summary.get("delta_vs_7d_avg", {})
            summary["delta_vs_7d_avg"][k] = round(lv - av, 3)

    return summary

def _summarize_training_load(db: Client, athlete_id: str, current_tss: float = 0.0) -> dict:
    try:
        tss_res = (
            db.table("tss_history")
            .select("date,daily_tss,ctl,atl,tsb")
            .eq("athlete_id", athlete_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        latest = tss_res.data[0] if (tss_res and tss_res.data) else None
    except Exception as e:
        latest = None
        err = str(e)
    else:
        err = None

    return {
        "most_recent_workout_tss": _safe_float(current_tss) or 0.0,
        "latest_pmc": {
            "date": (latest or {}).get("date"),
            "daily_tss": _safe_float((latest or {}).get("daily_tss")),
            "ctl": _safe_float((latest or {}).get("ctl")),
            "atl": _safe_float((latest or {}).get("atl")),
            "tsb": _safe_float((latest or {}).get("tsb")),
        } if latest else None,
        "error": err,
    }

def _summarize_athlete_profile(db: Client, athlete_id: str) -> dict:
    try:
        res = (
            db.table("athletes")
            .select("display_name,gender,timezone_offset_min,resting_hr,hrv_baseline,rhr_baseline,max_hr,threshold_hr,threshold_pace,ftp_watts,weight_kg,measurement_units")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = res.data or {}
    except Exception as e:
        return {"error": f"athlete_profile_query_failed: {str(e)}"}

    return {
        "display_name": row.get("display_name"),
        "gender": row.get("gender"),
        "measurement_units": row.get("measurement_units", "metric"),
        "timezone_offset_min": row.get("timezone_offset_min"),
        "anchors": {
            "resting_hr": _safe_int(row.get("resting_hr")),
            "rhr_baseline": _safe_int(row.get("rhr_baseline")),
            "hrv_baseline": _safe_float(row.get("hrv_baseline")),
            "max_hr": _safe_int(row.get("max_hr")),
            "threshold_hr": _safe_int(row.get("threshold_hr")),
            "threshold_pace": pace_with_unit(row.get("threshold_pace"), row.get("measurement_units")),
            "ftp_watts": _safe_int(row.get("ftp_watts")),
            "weight_kg": _safe_float(row.get("weight_kg")),
        },
        "anchors_rule": (
            "anchors are the athlete's current profile settings. Use them for every watt, pace and HR "
            "target. They override any FTP, threshold or weight number in memories or earlier messages. "
            "If an anchor is null, ask the athlete or call get_athlete_zones; never guess a number."
        ),
    }

def _load_conversation_history(db: Client, athlete_id: str, conversation_id: str, limit: int = 24) -> list[dict]:
    """
    Loads a small, ordered slice of messages for prompt context.
    """
    try:
        res = (
            db.table("coach_messages")
            .select("role,content,image_urls,attachments,created_at")
            .eq("athlete_id", athlete_id)
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True)
            .limit(max(1, min(int(limit), 80)))
            .execute()
        )
        rows = res.data or []
        rows.reverse()  # oldest -> newest
        # Keep only the essentials
        out: list[dict] = []
        for r in rows:
            role = r.get("role")
            content = str(r.get("content") or "")
            if role == "ai":
                content = _extract_athlete_message_from_text(content)
            out.append({
                "role": role,
                "content": content,
                "image_urls": r.get("image_urls") or [],
                "attachments": r.get("attachments") or [],
                "created_at": r.get("created_at"),
            })
        return out
    except Exception as e:
        return [{"role": "system", "content": f"history_load_failed: {str(e)}", "image_urls": []}]

# Per-athlete context cache — avoids 3 repeated DB queries across chat messages.
# Keys: athlete_id → (bio, profile, tss_base_dict, expires_at)
_context_parts_cache: dict[str, tuple[dict, dict, dict, float]] = {}
# Per process: other instances can't be told to drop it, so keep the TTL short.
_CONTEXT_CACHE_TTL = 60.0
_TIME_OF_DAY_GREETING_RE = re.compile(r"^\s*good\s+(morning|afternoon|evening)\b[\s,!.:-]*", re.IGNORECASE)


def _get_context_parts_cached(db: Client, athlete_id: str) -> tuple[dict, dict, dict]:
    """Return (biometrics, profile, training_load_base) from cache or fetch fresh."""
    now = time.time()
    cached = _context_parts_cache.get(athlete_id)
    if cached and now < cached[3]:
        return cached[0], cached[1], cached[2]
    bio = _summarize_biometrics(db, athlete_id)
    profile = _summarize_athlete_profile(db, athlete_id)
    tss_base = _summarize_training_load(db, athlete_id, current_tss=0.0)
    _context_parts_cache[athlete_id] = (bio, profile, tss_base, now + _CONTEXT_CACHE_TTL)
    return bio, profile, tss_base


def invalidate_context_cache(athlete_id: str) -> None:
    """Call after a data sync so the next message rebuilds context from fresh DB rows."""
    _context_parts_cache.pop(athlete_id, None)


def _time_of_day_greeting(local_now: Any) -> str:
    hour = int(getattr(local_now, "hour", 0))
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def _strip_leading_time_of_day_greeting(text: str | None) -> str:
    cleaned = _TIME_OF_DAY_GREETING_RE.sub("", (text or "").strip(), count=1).lstrip()
    if not cleaned:
        return cleaned
    return cleaned[:1].upper() + cleaned[1:]


def _calendar_context_for_offset(timezone_offset_min: int) -> dict[str, Any]:
    local_now = local_datetime_from_timezone_offset(timezone_offset_min)
    today = local_now.date()
    tomorrow = today + timedelta(days=1)
    upcoming_weekdays = {
        (today + timedelta(days=i)).strftime("%A"): (today + timedelta(days=i)).isoformat()
        for i in range(7)
    }
    return {
        "current_local_date": today.isoformat(),
        "current_local_weekday": today.strftime("%A"),
        "current_local_datetime": local_now.isoformat(timespec="seconds"),
        "tomorrow_date": tomorrow.isoformat(),
        "tomorrow_weekday": tomorrow.strftime("%A"),
        "upcoming_weekdays": upcoming_weekdays,
    }


def _athlete_local_calendar(db: Client, athlete_id: str, timezone_offset_min: int | None = None) -> dict[str, Any]:
    _, profile, _ = _get_context_parts_cached(db, athlete_id)
    offset = coerce_timezone_offset_min(
        profile.get("timezone_offset_min") if timezone_offset_min is None else timezone_offset_min
    )
    return _calendar_context_for_offset(offset)


_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _message_mentions(message: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", message or "", flags=re.IGNORECASE))


def _message_has_explicit_iso_date(message: str) -> bool:
    return bool(_ISO_DATE_RE.search(message or ""))


def _calendar_preface(message: str, calendar: dict[str, Any]) -> str:
    upcoming_weekdays = calendar.get("upcoming_weekdays") or {}
    weekday_lines = "\n".join(
        f"- {weekday}: {iso_date}"
        for weekday, iso_date in upcoming_weekdays.items()
    )
    return (
        "[ATHLETE-LOCAL CALENDAR]\n"
        f"Today is {calendar['current_local_weekday']}, {calendar['current_local_date']}.\n"
        f"Tomorrow is {calendar['tomorrow_weekday']}, {calendar['tomorrow_date']}.\n"
        "Upcoming weekday dates:\n"
        f"{weekday_lines}\n"
        "Resolve relative dates and named weekdays from these values, not from UTC/server timestamps.\n"
        "For follow-up messages, preserve the previously discussed workout date unless the athlete clearly changes it.\n"
        "[ATHLETE MESSAGE]\n"
        f"{message}"
    )


def _normalize_relative_tool_dates(
    tool_name: str,
    args: dict[str, Any],
    *,
    message: str,
    calendar: dict[str, Any],
) -> dict[str, Any]:
    """
    Deterministically correct model-chosen dates for relative workout requests.

    The LLM can still infer dates from UTC or stale chat history. For write tools,
    the backend is the source of truth for common relative dates.
    """
    if tool_name != "schedule_workout":
        return args
    if _message_has_explicit_iso_date(message):
        return args

    normalized = dict(args)
    if _message_mentions(message, "tomorrow"):
        normalized["date"] = calendar["tomorrow_date"]
    elif _message_mentions(message, "today"):
        normalized["date"] = calendar["current_local_date"]
    else:
        upcoming_weekdays = calendar.get("upcoming_weekdays") or {}
        for weekday, iso_date in upcoming_weekdays.items():
            if _message_mentions(message, weekday):
                normalized["date"] = iso_date
                break
    return normalized


def _month_day_labels(iso_date: str) -> list[str]:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return []
    suffix = "th" if 11 <= (d.day % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    base = f"{d.strftime('%B')} {d.day}"
    return [base, f"{base}{suffix}"]


def _calendar_tool_result_reminder(planned_dates: list[str], calendar: dict[str, Any]) -> str | None:
    labels: list[str] = []
    for planned_date in planned_dates:
        if planned_date == calendar.get("tomorrow_date"):
            labels.append(f"{planned_date} is tomorrow ({calendar.get('tomorrow_weekday')}).")
        elif planned_date == calendar.get("current_local_date"):
            labels.append(f"{planned_date} is today ({calendar.get('current_local_weekday')}).")
    if not labels:
        return None
    return (
        "[CALENDAR REMINDER FOR FINAL RESPONSE]\n"
        + " ".join(labels)
        + " Use this wording when confirming scheduled workouts."
    )


def _correct_relative_date_language(text: str, planned_dates: list[str], calendar: dict[str, Any]) -> str:
    corrected = text or ""
    for planned_date in planned_dates:
        if planned_date != calendar.get("tomorrow_date"):
            continue
        corrected = re.sub(r"\b(to|for) today\b", r"\1 tomorrow", corrected, flags=re.IGNORECASE)
        corrected = re.sub(r"\btoday's\b", "tomorrow's", corrected, flags=re.IGNORECASE)
        for label in _month_day_labels(planned_date):
            escaped = re.escape(label)
            corrected = re.sub(
                rf"\btoday(\s*,?\s*)({escaped})",
                r"tomorrow\1\2",
                corrected,
                flags=re.IGNORECASE,
            )
            corrected = re.sub(
                rf"\btoday(\s*\(\s*)({escaped})(\s*\))",
                r"tomorrow\1\2\3",
                corrected,
                flags=re.IGNORECASE,
            )
    return corrected


def _build_system_context(
    db: Client,
    athlete_id: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
    memories: list[dict] | None = None,
    timezone_offset_min: int | None = None,
) -> str:
    bio, profile, tss_base = _get_context_parts_cached(db, athlete_id)
    offset = coerce_timezone_offset_min(
        profile.get("timezone_offset_min") if timezone_offset_min is None else timezone_offset_min
    )
    calendar = _calendar_context_for_offset(offset)
    today = calendar["current_local_date"]
    profile = {**profile, "timezone_offset_min": offset}
    # Patch current workout TSS (varies per message) into the cached training load dict.
    training_load = {**tss_base, "most_recent_workout_tss": _safe_float(current_tss) or 0.0}
    ctx: dict = {
        "date": today,
        **calendar,
        "timezone_offset_min": offset,
        "calendar_rules": {
            "today": "Resolve today from current_local_date in the athlete's timezone.",
            "tomorrow": "Resolve tomorrow from tomorrow_date in the athlete's timezone.",
            "named_weekdays": "Resolve weekday names from upcoming_weekdays.",
            "followups": "If the athlete clarifies a plan with words like this, that, it, or all, keep the previously discussed workout date unless they clearly change it.",
            "memory_dates": MEMORY_CONTEXT_RULE,
        },
        "athlete_id": athlete_id,
        "training_load": training_load,
        "biometrics": bio,
        "athlete_profile": profile,
    }
    if memories:
        ctx["memories"] = memories_for_context(memories, today)
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": _load_conversation_history(db, athlete_id, conversation_id, limit=24),
        }
    recent = recent_workouts_teaser(db, athlete_id, limit=2)
    if recent:
        ctx["recent_workouts"] = recent
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(with_duration_text(ctx), ensure_ascii=False) + "\n[END CONTEXT]"


def detect_anomalies(db: Client, athlete_id: str) -> dict[str, Any] | None:
    """
    Returns a dict with triggered signals if any severe rule fires; otherwise None.
    Thresholds: HRV z < -1.5, sleep_debt > 90 min, RHR > 7d avg + 5, TSB < -30, skin_temp_dev > 0.6°C.
    """
    signals: list[dict[str, Any]] = []

    # --- HRV z (30-row window, 7d EWMA baseline on prior readings; match /v1/athlete/state) ---
    try:
        bio_window_res = (
            db.table("biometrics")
            .select("date,hrv_rmssd,resting_hr,sleep_duration_min,sleep_debt_min,skin_temp")
            .eq("athlete_id", athlete_id)
            .order("date", desc=True)
            .limit(30)
            .execute()
        )
        window_rows = list(reversed(bio_window_res.data or []))
    except Exception:
        window_rows = []

    def _series(field: str) -> np.ndarray:
        vals: list[float] = []
        for r in window_rows:
            v = r.get(field)
            try:
                if v is None:
                    continue
                fv = float(v)
                if fv == 0 and field == "hrv_rmssd":
                    continue
                vals.append(fv)
            except (TypeError, ValueError):
                continue
        return np.array(vals, dtype=float) if vals else np.array([], dtype=float)

    hrv_series = _series("hrv_rmssd")
    latest_row = window_rows[-1] if window_rows else {}
    hrv_latest = latest_row.get("hrv_rmssd")
    if hrv_latest is not None and len(hrv_series) > 0:
        hrv_z, hrv_base, hrv_sd = compute_z_score(
            float(hrv_latest),
            hrv_series[:-1] if len(hrv_series) > 1 else hrv_series,
            span=7,
        )
        if hrv_z < -1.5:
            signals.append({
                "metric": "hrv_z",
                "value": round(hrv_z, 3),
                "threshold": -1.5,
                "hrv_rmssd": float(hrv_latest),
                "baseline_ewma": round(hrv_base, 2) if hrv_base is not None else None,
            })

    # --- Sleep debt ---
    sleep_debt_min = latest_row.get("sleep_debt_min")
    if sleep_debt_min is None:
        sdur = _safe_int(latest_row.get("sleep_duration_min"))
        if sdur is not None:
            sleep_debt_min = max(0, 480 - sdur)
    if sleep_debt_min is not None and float(sleep_debt_min) > 90:
        signals.append({
            "metric": "sleep_debt_min",
            "value": float(sleep_debt_min),
            "threshold": 90,
        })

    # --- RHR & Skin Temp vs 7d average ---
    # Fetch athlete units to report anomalies correctly
    profile = _summarize_athlete_profile(db, athlete_id)
    units = profile.get("measurement_units", "metric")
    
    bio_summary = _summarize_biometrics(db, athlete_id, units=units)
    if bio_summary.get("available"):
        # RHR Check
        lr = _safe_int(bio_summary["latest"].get("resting_hr"))
        av = _safe_float(bio_summary["avg_7d"].get("resting_hr"))
        if lr is not None and av is not None and lr > av + 5:
            signals.append({
                "metric": "resting_hr_delta",
                "resting_hr": lr,
                "avg_7d_rhr": round(av, 1),
                "threshold_bpm_above_avg": 5,
            })
            
        # Skin Temp Check (Actual Deviation)
        # We compare absolute values in Celsius to maintain scientific threshold of 0.6°C
        # but the bio_summary "latest" and "avg_7d" keys are already unit-converted.
        # So we fetch raw values from rows for calculation.
        def _get_raw_avg(key: str) -> float | None:
            vals = [_safe_float(r.get(key)) for r in window_rows[-7:] if _safe_float(r.get(key)) is not None]
            return sum(vals) / len(vals) if vals else None

        raw_latest = _safe_float(latest_row.get("skin_temp"))
        raw_avg = _get_raw_avg("skin_temp")
        
        if raw_latest is not None and raw_avg is not None:
            deviation_c = raw_latest - raw_avg
            if deviation_c > 0.6:
                # Reporting unit-aware values for the LLM
                reported_latest = bio_summary["latest"]["skin_temp"]
                reported_avg = bio_summary["avg_7d"]["skin_temp"]
                reported_unit = "°F" if units == "imperial" else "°C"
                
                signals.append({
                    "metric": "skin_temp_deviation",
                    "deviation_celsius": round(deviation_c, 3),
                    "latest_value": f"{reported_latest}{reported_unit}",
                    "baseline_avg": f"{reported_avg}{reported_unit}",
                    "threshold_celsius": 0.6,
                })

    # --- TSB ---
    tl = _summarize_training_load(db, athlete_id, 0.0)
    pmc = tl.get("latest_pmc") or {}
    tsb_val = _safe_float(pmc.get("tsb"))
    if tsb_val is not None and tsb_val < -30:
        signals.append({
            "metric": "tsb",
            "value": tsb_val,
            "threshold": -30,
        })

    if not signals:
        return None
    return {"triggered": True, "signals": signals}


def build_initialization_message(
    athlete_id: str,
    db: Client,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
) -> tuple[str, bool]:
    """
    Proactive first message when chat mounts, or a standard greeting.
    Returns (message_text, is_proactive).
    """
    anomalies = detect_anomalies(db, athlete_id)
    instructions = load_coach_instructions()
    context_block = _build_system_context(
        db,
        athlete_id,
        current_tss=0.0,
        conversation_id=None,
        timezone_offset_min=timezone_offset_min,
    )
    _, profile, _ = _get_context_parts_cached(db, athlete_id)
    offset = coerce_timezone_offset_min(
        profile.get("timezone_offset_min") if timezone_offset_min is None else timezone_offset_min
    )
    local_now = local_datetime_from_timezone_offset(offset)
    greeting = _time_of_day_greeting(local_now)
    effective_model = model_name or settings.GEMINI_MODEL

    if anomalies:
        directive = (
            "[PROACTIVE CHECK]\nThe following severe anomalies were detected (JSON):\n"
            + json.dumps(anomalies, ensure_ascii=False)
            + "\n\nWrite exactly 2–3 sentences. Name the triggering metric(s). Recommend a decisive action. "
            "Do not include a time-of-day greeting such as Good morning, Good afternoon, or Good evening. "
            "ASTRAPHE voice: conversational, supportive, and measured. Use emoji only if it adds clear signal; do not make it a default closer. Wrap your final message in <response> ... </response> tags."
        )
    else:
        directive = (
            "[INITIAL GREETING]\nNo severe anomaly triggers fired. "
            "Write at most 2 sentences, context-aware, and cite TSB or HRV from the context. "
            "Do not include a time-of-day greeting such as Good morning, Good afternoon, or Good evening; the server will add the correct local greeting. "
            "ASTRAPHE voice: conversational, supportive, and measured. Use emoji only if it adds clear signal; do not make it a default closer. Wrap your final message in <response> ... </response> tags."
        )

    prompt = f"{instructions}\n\n{context_block}\n\n{directive}"
    try:
        fallback_model = (getattr(settings, "GEMINI_FALLBACK_MODEL", "") or "").strip()
        candidates: list[str] = [effective_model]
        if fallback_model and fallback_model not in candidates:
            candidates.append(fallback_model)

        last_err: Exception | None = None
        text = ""
        for idx, model in enumerate(candidates):
            for attempt in range(3):
                try:
                    gemini_quota.wait_for_slot(model, max_wait_sec=15.0)
                    response = _client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            max_output_tokens=256,
                            temperature=0.35,
                        ),
                    )
                    text = _extract_athlete_message_from_model_output(response)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    is_transient = any(
                        k in err_str
                        for k in ("500", "503", "INTERNAL", "overloaded", "UNAVAILABLE", "high demand")
                    )
                    if attempt < 2 and is_transient:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    break

            if text and not _is_failed_extraction(text):
                break
            text = ""
            if idx == 0 and len(candidates) > 1 and (
                last_err is None or _should_fallback_chat_model(str(last_err))
            ):
                continue
            break
    except Exception as e:
        # Never surface provider errors directly in the UI.
        text = ""
    text = _strip_leading_time_of_day_greeting(text)
    if _is_failed_extraction(text):
        text = ""
    if not anomalies and text:
        text = f"{greeting}. {text}"
    if not text:
        # Deterministic, non-error fallback.
        if anomalies:
            text = "I’m seeing a couple signals that suggest we should keep today low-stress. Want me to propose a recovery-focused plan for the next 24–48 hours?"
        else:
            text = f"{greeting}. What do you want to focus on today—training plan, recovery, or a specific workout?"
    return text, bool(anomalies)


# Photos the athlete attached (coach-uploads bucket). Only the newest user messages with
# photos are sent, to bound tokens and download time.
_IMAGE_MESSAGES_SENT = 2
_IMAGES_PER_TURN = 6
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_COACH_UPLOAD_PATH_RE = re.compile(r"/storage/v1/object/(?:sign|public|authenticated)/coach-uploads/([^?#]+)")
_IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
}


def _coach_upload_path(url: str) -> str | None:
    """Object path inside the coach-uploads bucket for a (signed) storage URL, else None.

    Only our own bucket's paths are accepted (never an arbitrary URL), and downloads go
    through the athlete's own client, so storage RLS limits them to their own folder.
    """
    from urllib.parse import unquote

    m = _COACH_UPLOAD_PATH_RE.search(url or "")
    if not m:
        return None
    path = unquote(m.group(1))
    if not path.startswith("coach/") or ".." in path.split("/"):
        return None
    return path


_SIGNED_UPLOAD_RE = re.compile(r"(/storage/v1/object/sign/coach-uploads/[^?#]+\?token=[A-Za-z0-9._-]+)")


def _download_upload(db: Any, url: str, path: str) -> bytes | None:
    """Fetch a chat photo. The app stores signed URLs (the bucket is private); their token
    grants read access to that one object. The request always goes to our own Supabase
    (settings.SUPABASE_URL), never to the host in the stored URL. Without a token, fall
    back to the athlete's client."""
    m = _SIGNED_UPLOAD_RE.search(url or "")
    if m:
        r = httpx.get(settings.SUPABASE_URL.rstrip("/") + m.group(1), timeout=15.0)
        r.raise_for_status()
        return r.content
    return db.storage.from_("coach-uploads").download(path)


def _load_image_parts(db: Any, urls: list[str], limit: int = _IMAGES_PER_TURN) -> list[types.Part]:
    parts: list[types.Part] = []
    for url in urls:
        if len(parts) >= limit:
            break
        path = _coach_upload_path(url)
        if not path:
            continue
        mime = _IMAGE_MIME.get(path.rsplit(".", 1)[-1].lower())
        if not mime:
            continue
        try:
            data = _download_upload(db, url, path)
        except Exception as e:
            logger.warning("[coach] image download failed path=%s: %r", path, e)
            continue
        if not data or len(data) > _MAX_IMAGE_BYTES:
            continue
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    return parts


# Document text replayed from earlier messages, newest first, across the whole history.
_HISTORY_DOC_CHARS = 60000


def _attachment_preface(history: list[dict]) -> dict[int, str]:
    """Per history index, the attached documents' text to put before that user message.

    The newest user message is skipped: it is the one being answered, and its documents
    already ride along with the current turn's message. Older documents are replayed
    newest first until _HISTORY_DOC_CHARS, so a plan uploaded a few turns ago stays visible.
    """
    last_user = max((i for i, r in enumerate(history) if r.get("role") == "user"), default=-1)
    budget = _HISTORY_DOC_CHARS
    out: dict[int, str] = {}
    for i in range(len(history) - 1, -1, -1):
        r = history[i]
        if i == last_user or r.get("role") != "user":
            continue
        parts: list[str] = []
        for d in r.get("attachments") or []:
            if not isinstance(d, dict):
                continue
            text = str(d.get("content") or "")
            name = str(d.get("name") or "document")
            if budget <= 0 or not text:
                parts.append(f"[ATTACHED DOCUMENT: {name} (text omitted)]")
                continue
            text = text[:budget]
            budget -= len(text)
            parts.append(f"[ATTACHED DOCUMENT: {name}]\n{text}")
        if parts:
            out[i] = "\n\n".join(parts)
    return out


def _history_to_gemini_contents(
    history: list[dict],
    image_parts: Callable[[list[str]], list[types.Part]] | None = None,
) -> list[types.Content]:
    """Map coach_messages rows to Gemini Content (user / model).

    With `image_parts`, the photos on the newest user messages are sent as image parts
    (they used to be stored and shown in the chat but never reached the model).
    """
    out: list[types.Content] = []
    docs_before = _attachment_preface(history)
    with_images: set[int] = set()
    if image_parts is not None:
        for i in range(len(history) - 1, -1, -1):
            if len(with_images) >= _IMAGE_MESSAGES_SENT:
                break
            if history[i].get("role") == "user" and history[i].get("image_urls"):
                with_images.add(i)
    for idx, r in enumerate(history):
        raw_role = (r.get("role") or "").strip()
        content = (r.get("content") or "").strip()
        if idx in docs_before:
            content = f"{docs_before[idx]}\n\n[ATHLETE MESSAGE]\n{content}"
        if not content:
            continue
        if raw_role not in ("user", "ai"):
            continue
        if raw_role == "ai":
            content = _extract_athlete_message_from_text(content).strip()
            if not content:
                continue
        grole = "user" if raw_role == "user" else "model"
        parts = [types.Part.from_text(text=content)]
        if idx in with_images and image_parts is not None:
            parts.extend(image_parts(list(r.get("image_urls") or [])))
        out.append(types.Content(role=grole, parts=parts))
    return out


def _extract_grounding_sources(response: Any) -> list[dict[str, str]]:
    """Parse Google Search grounding chunks into citation dicts for the client."""
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        cands = getattr(response, "candidates", None)
        if not cands:
            return []
        cand0 = cands[0]
        gmd = getattr(cand0, "grounding_metadata", None)
        if gmd is None:
            return []
        chunks = getattr(gmd, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            title = getattr(web, "title", None) or ""
            uri = getattr(web, "uri", None) or getattr(web, "url", None) or ""
            uri = uri.strip()
            if not uri or uri in seen:
                continue
            seen.add(uri)
            sources.append({"title": str(title).strip(), "url": uri})
    except Exception:
        return sources
    return sources


def _extract_non_thought_text_from_response(
    response: Any,
    *,
    allow_text_fallback: bool = True,
) -> str:
    """
    Join visible text parts from a Gemini response while dropping thought parts.

    Some Gemini thinking models expose reasoning as `part.thought=True`; Gemma-style
    models may not, so this is one layer before the XML/fallback sanitizer.

    When every structured part is thought-only, fall back to ``response.text`` or the
    joined thought text so Gemma 4 does not produce empty coach replies.
    """
    text_parts: list[str] = []
    thought_parts: list[str] = []
    saw_structured_parts = False
    try:
        candidates = getattr(response, "candidates", None) or []
        candidate = candidates[0] if candidates else None
        content = getattr(candidate, "content", None) if candidate is not None else None
        parts = getattr(content, "parts", None) or []
        for part in parts:
            saw_structured_parts = True
            if getattr(part, "function_call", None) or getattr(part, "function_response", None):
                continue
            text = getattr(part, "text", None)
            if not text:
                continue
            if getattr(part, "thought", False):
                thought_parts.append(str(text))
                continue
            text_parts.append(str(text))
    except Exception:
        text_parts = []

    joined = "".join(text_parts).strip()
    if joined:
        return joined

    if allow_text_fallback:
        fallback_text = (getattr(response, "text", None) or "").strip()
        if fallback_text:
            return fallback_text

    # Gemma 4 sometimes labels the entire athlete reply as thought=True, with the reply still
    # marked (a <response> block or a "Draft:" line). Anything else in a thought part is
    # reasoning and never reaches the athlete: a Qwen turn that ended mid-thought
    # (reasoning_content, empty content) was sent as the coach's reply. Returning "" lets the
    # caller recover with a proper wrap-up reply.
    if thought_parts:
        thought = "".join(thought_parts).strip()
        return thought if (_RESPONSE_RE.search(thought) or _DRAFT_MARKER_RE.search(thought)) else ""

    if allow_text_fallback and not saw_structured_parts:
        return (getattr(response, "text", None) or "").strip()
    return ""


def _extract_athlete_message_from_model_output(response: Any) -> str:
    """Extract visible model text and pass it to the response parser."""
    raw_text = _extract_non_thought_text_from_response(response)
    return _extract_athlete_message_from_text(raw_text)


_EXTRACTION_FAILURE_MESSAGE = "I encountered an error processing your request."


def _is_failed_extraction(text: str) -> bool:
    cleaned = (text or "").strip()
    return not cleaned or cleaned == _EXTRACTION_FAILURE_MESSAGE


_RESPONSE_RE = re.compile(r"<response>(.*?)</response>", re.DOTALL | re.IGNORECASE)
_SCRATCHPAD_RE = re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL | re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THOUGHT_BLOCK_RE = re.compile(r"(?:^|\n)\s*THOUGHT:\s*.*?(?=\n\s*\n|$)", re.DOTALL | re.IGNORECASE)
_READY_MARKER_RE = re.compile(r"\*Ready\.\*", re.IGNORECASE)
_DRAFT_MARKER_RE = re.compile(r"(?:^|\n)\s*(?:\*+\s*)?Draft:\s*", re.IGNORECASE | re.MULTILINE)
_PLANNING_DUMP_MARKERS = (
    "* trigger:",
    "trigger:",
    "* goal:",
    "goal:",
    "* athlete:",
    "athlete:",
    "* current state:",
    "current state:",
    "constraint check:",
    "metric to cite:",
    "* action:",
    "action:",
    "* draft:",
    "draft:",
)


_REASONING_MARKERS = (
    "the athlete",
    "the user",
    "let me ",
    "hmm",
    "i should ",
    "available tools",
    "there's no tool",
    "no tool for",
    "direct tool",
    "write the response",
    "my response",
    "the response",
    "should i ",
)


def _looks_like_reasoning(text: str) -> bool:
    """Prose chain-of-thought in the visible text (no <response> block): it talks about "the
    athlete" and its own process ("Let me...", "Hmm", tools), which a reply to the athlete
    doesn't. Several distinct markers, so a normal reply that says "let me know" passes.
    (Prod: an 8k-character "The athlete said... Hmm... Let me save memories now." was sent.)"""
    low = (text or "").lower()
    return sum(1 for m in _REASONING_MARKERS if m in low) >= 3


def _looks_like_planning_dump(text: str) -> bool:
    low = (text or "").lower()
    if not low:
        return False
    hits = sum(1 for marker in _PLANNING_DUMP_MARKERS if marker in low)
    return hits >= 2 or ("trigger:" in low and "draft:" in low)


def _dedupe_repeated_suffix(text: str) -> str:
    """Gemma sometimes repeats the draft reply inline after an emoji."""
    t = (text or "").strip()
    if len(t) < 80:
        return t
    probe = t[: min(48, len(t))]
    second = t.find(probe, len(probe))
    if second > 0:
        return t[:second].strip()
    return t


def _extract_draft_or_final_reply(text: str) -> str:
    """Pull athlete-facing copy from Gemma-style planning bullet dumps."""
    t = (text or "").strip()
    if not t:
        return ""

    draft_matches = list(_DRAFT_MARKER_RE.finditer(t))
    if draft_matches:
        segment = t[draft_matches[-1].end() :].strip()
        segment = re.split(r"\n\s*(?:\*+\s*)?Draft:\s*", segment, maxsplit=1, flags=re.I)[0].strip()
        return _dedupe_repeated_suffix(segment)
    return ""


_COACH_REPLY_START_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"Because (?:the |your |with |how )|"
    r"Given how (?:much |your )|"
    r"Hey \w|"
    r"Here is how (?:I )?recommend|"
    r"Here are|"
    r"That \d|"
    r"That (?:is|was|sounds|looks|effort)|"
    r"Your (?:sleep|recovery|HRV|CTL|ATL|TSB|readiness|ride|bike)|"
    r"Sounds like|"
    r"I(?:'m| am) excited|"
    r"To answer your question|"
    r"The short answer|"
    r"Yes(?:,|\s|-)|"
    r"Nice work|"
    r"Looking at your|"
    r"I would (?:actually )?recommend|"
    r"I'd (?:actually )?recommend|"
    r"Light spin only|"
    r"Rest today"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_athlete_message_from_text(raw_text: str) -> str:
    """
    Extract the athlete-facing message from XML output or sanitized fallback text.
    """
    raw = (raw_text or "").strip()
    # Reasoning some models write into the visible text: <think>...</think>, or an unclosed
    # <think> (the turn ended mid-thought) where everything after it is reasoning.
    raw = _THINK_RE.sub("", raw)
    if "<think>" in raw.lower():
        raw = raw[: raw.lower().index("<think>")]
    raw = raw.strip()
    if not raw:
        return ""

    # Primary contract: only text inside the final <response> reaches the athlete.
    matches = list(_RESPONSE_RE.finditer(raw))
    if matches:
        cleaned = _strip_internal_reasoning(matches[-1].group(1))
        return cleaned or _EXTRACTION_FAILURE_MESSAGE

    raw = _SCRATCHPAD_RE.sub("", raw).strip()
    raw = _THOUGHT_BLOCK_RE.sub("", raw).strip()

    draft = _extract_draft_or_final_reply(raw)
    if draft:
        cleaned = _strip_internal_reasoning(draft)
        if cleaned and not _looks_like_planning_dump(cleaned):
            return cleaned

    cleaned = _strip_internal_reasoning(raw)
    if cleaned and _looks_like_planning_dump(cleaned):
        draft = _extract_draft_or_final_reply(cleaned)
        if draft:
            cleaned = _strip_internal_reasoning(draft)
        elif _looks_like_planning_dump(cleaned):
            cleaned = ""
    if cleaned and _looks_like_reasoning(cleaned):
        # Reasoning with no <response>: not a reply. Failing here lets the caller ask again.
        cleaned = ""
    return cleaned or _EXTRACTION_FAILURE_MESSAGE


def _strip_internal_reasoning(text: str) -> str:
    """
    Backstop sanitizer: if the model emits chain-of-thought style scaffolding, drop it.
    """
    t = _SCRATCHPAD_RE.sub("", (text or "")).strip()
    t = _THOUGHT_BLOCK_RE.sub("", t).strip()
    if not t:
        return ""

    # Model sometimes ends planning with *Ready.* immediately before the athlete reply.
    ready_parts = _READY_MARKER_RE.split(t)
    if len(ready_parts) > 1:
        t = ready_parts[-1].strip()

    # Long inline dumps: jump to the first coach-voice paragraph.
    start = _COACH_REPLY_START_RE.search(t)
    if start:
        prefix = t[: start.start()].lower()
        has_meta_preface = any(
            marker in prefix
            for marker in (
                "the user",
                "user is asking",
                "plan:",
                "constraint check",
                "final response",
                "scratchpad",
            )
        )
        if start.start() > 80 or has_meta_preface:
            t = t[start.start() :].strip()

    bad_prefixes = (
        "user goal:",
        "user wants to",
        "the user is",
        "user is asking",
        "current date",
        "current tsb",
        "current hrv",
        "current ctl",
        "current atl",
        "target race",
        "race context:",
        "race details:",
        "search results",
        "search result",
        "the search results",
        "the race is",
        "water temp",
        "wetsuits are",
        "upcoming load",
        "constraint check",
        "metric to cite",
        "current state",
        "trigger:",
        "goal:",
        "action:",
        "draft:",
        "role:",
        "wait,",
        "actually,",
        "self-correction",
        "drafting the response",
        "drafting final response",
        "response structure:",
        "final check",
        "final response construction",
        "final polish",
        "final plan:",
        "final response:",
        "final response structure:",
        "one more thing:",
        "let's double check",
        "let's refine",
        "let's say they",
        "refining the",
        "table construction:",
        "step 1:",
        "step 2:",
        "step 3:",
        "the priority is",
        "answer directly",
        "acknowledge",
        "validate",
        "address the",
        "provide actionable",
        "remind them",
        "ask if",
        "note that",
        "cite ",
        "include ",
        "use ",
        "make sure",
        "metrics to mention",
        "metric check",
        "mention ",
        "connect to",
        "list ",
        "explain why",
        "since i don't",
        "i will advise",
        "i'll structure",
        "plan:",
        "the pemi loop will likely",
    )

    planning_bullet_markers = (
        "current date",
        "current tsb",
        "current hrv",
        "current ctl",
        "current atl",
        "target race",
        "race context",
        "race details",
        "search results",
        "the race is",
        "water temp",
        "wetsuits are",
        "upcoming load",
        "step 1",
        "step 2",
        "step 3",
        "the user",
        "wait,",
        "trigger",
        "goal:",
        "action:",
        "athlete:",
        "current state",
        "metric to cite",
        "constraint check",
        "final check",
        "final plan",
        "final response",
        "drafting",
        "self-correction",
        "one more thing",
        "let's refine",
        "let's double",
        "pemi loop will likely",
        "simulate the",
        "answer directly",
        "acknowledge",
        "validate",
        "address the",
        "provide actionable",
        "remind them",
        "ask if",
        "note that",
        "cite ",
        "include ",
        "use ",
        "make sure",
        "metrics to mention",
        "metric check",
        "mention ",
        "connect to",
        "explain why",
    )

    lines = [ln.rstrip() for ln in t.splitlines()]

    def is_meta_line(ln: str) -> bool:
        low = ln.strip().lower()
        if not low:
            return False
        if any(low.startswith(p) for p in bad_prefixes):
            return True
        if low.startswith(("current metrics:", "target date:", "timeframe:", "persona:", "rule:", "action requested:")):
            return True
        if re.match(r"^[a-z][a-z0-9 /_-]{2,48}:$", low):
            if any(m in low for m in planning_bullet_markers):
                return True
        if re.match(r"^\*\s+", ln.strip()):
            if any(m in low for m in planning_bullet_markers):
                return True
        if re.match(r"^step\s+\d+:", low):
            return True
        return False

    def looks_like_reply(ln: str) -> bool:
        s = ln.strip()
        if not s:
            return False
        if s.startswith("Day | Discipline | Duration | Intensity/Zone"):
            return True
        if s.startswith("Day\tDiscipline") or s.startswith("Day |"):
            return True
        low = s.lower()
        coach_openings = (
            "because the ",
            "because your ",
            "because with ",
            "given how ",
            "hey ",
            "here is how",
            "here are",
            "that ",
            "your ",
            "sounds like",
            "to answer your question",
            "the short answer",
            "yes,",
            "yes ",
            "nice work",
            "looking at your",
            "i would ",
            "i'd ",
            "light spin",
            "rest today",
        )
        if any(low.startswith(o) for o in coach_openings):
            return True
        metric_meta_prefixes = (
            "remind them",
            "ask if",
            "mention ",
            "metric check",
            "metrics to mention",
            "constraint check",
            "cite ",
            "include ",
            "use ",
            "note that",
            "make sure",
        )
        if (
            any(k in low for k in ("ctl", "atl", "tsb", "hrv", "rmssd", "sleep score"))
            and (("." in s) or (":" in s))
            and not any(low.startswith(p) for p in metric_meta_prefixes)
        ):
            return True
        return False

    first_reply_idx = next((idx for idx, ln in enumerate(lines) if looks_like_reply(ln)), None)
    if first_reply_idx is not None and first_reply_idx > 0:
        prior = lines[:first_reply_idx]
        saw_meta_preface = any(
            is_meta_line(ln)
            or ln.strip().lower().startswith(("the user", "user "))
            for ln in prior
        )
        if saw_meta_preface:
            return "\n".join(ln for ln in lines[first_reply_idx:] if ln.strip()).strip()

    i = 0
    while i < len(lines):
        if looks_like_reply(lines[i]):
            break
        if not lines[i].strip() or is_meta_line(lines[i]):
            i += 1
            continue
        low = lines[i].strip().lower()
        draft_match = re.match(r"^(?:\*+\s*)?draft:\s*(.+)$", lines[i].strip(), re.I)
        if draft_match and draft_match.group(1).strip():
            return _dedupe_repeated_suffix(draft_match.group(1).strip())
        if low.startswith(("wait", "actually", "final")) or (
            low.startswith("draft:") and not draft_match
        ) or (
            low.startswith("the user") and "asking" in low
        ):
            i += 1
            continue
        break

    out = "\n".join(ln for ln in lines[i:] if ln.strip()).strip()
    if out and not _looks_like_planning_dump(out):
        return out

    if _looks_like_planning_dump(t):
        draft = _extract_draft_or_final_reply(t)
        if draft:
            return _dedupe_repeated_suffix(draft)
        return ""

    return t



def _coach_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    status: str,
    **extra: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback({"status": status, **extra})
    except Exception:
        pass

# Tool names whose handlers actually write data (see coach_tools.TOOL_HANDLERS).
# Used only to word the post-tool-call failure fallback honestly — claiming
# "I updated your status" is fine if one of these just ran, but false (and
# misleading) if the hop only ran read-only lookups.
def _tool_names_from_last_function_response(contents: list) -> list[str]:
    """
    Scan `contents` backwards for the most recent turn carrying
    function_response parts, and return the tool name(s) those responses
    are for.

    Needed for two cases `contents[-1]` alone misses (Copilot review on
    PR #17):
    - A calendar reminder turn (see _calendar_tool_result_reminder) can be
      appended right after a function_response turn, so contents[-1] is
      plain text with no function_response by the time the *next* hop's
      call fails — the actual tool result is one turn further back.
    - The deterministic clear_training_plans backstop below injects a
      function_response directly, without ever going through the model's
      own function_call path, so last_tool_names (only populated from
      model-issued calls) never sees it.

    Every hop transition only happens because the previous hop called at
    least one tool (the loop returns immediately on plain text), so the
    most recent function_response turn is always the one relevant to
    *this* failure — there's no risk of picking up a stale tool call from
    several hops back.
    """
    for content in reversed(contents):
        parts = getattr(content, "parts", None) or []
        names = [
            getattr(p.function_response, "name", None)
            for p in parts
            if getattr(p, "function_response", None) is not None
        ]
        names = [n for n in names if n]
        if names:
            return names
    return []


# Canned replies get_coach_response_agentic returns (rather than raising) when it can't finish.
# Callers that send the reply somewhere a person didn't ask for it (the Photon post-workout text)
# check COACH_FAILURE_REPLIES so an error message is never sent as if it were a coaching note.
COACH_PARTIAL_ERROR_REPLY = (
    "I went ahead and made that change, but hit an error putting together "
    "the full explanation. Let me know if you'd like me to try again."
)
COACH_ERROR_REPLY = (
    "Sorry, I ran into an error putting that response together. "
    "Could you try asking again?"
)
COACH_INCOMPLETE_REPLY = "Unable to complete coach response."

SCRATCHPAD_UNAVAILABLE_NOTE = (
    "\n\n[SESSION NOTE: The internal_scratchpad tool is not available in this session. Do your "
    "reasoning silently (never print it), call only the tools you actually need, and then give "
    "your final answer in the <response> block.]"
)
COACH_FAILURE_REPLIES = frozenset({COACH_PARTIAL_ERROR_REPLY, COACH_ERROR_REPLY, COACH_INCOMPLETE_REPLY})

_WRAP_UP_NOTE = (
    "[SYSTEM] You have used all tool calls for this message. Do not call tools. Reply to the "
    "athlete now: say plainly what you did (from the tool results above, with dates), what is "
    "not done yet, and offer to continue in the next message."
)


# Gemini 3 rejects a request whose earlier function_call parts carry no thought_signature, and
# tool calls made by the self-hosted chat model never have one. Google's documented placeholder
# for history that came from another model lets Gemini take over a turn mid-way.
_PLACEHOLDER_THOUGHT_SIGNATURE = b"skip_thought_signature_validator"

# Seconds of a turn's time budget kept for the Gemini fallback, and the shortest request the
# self-hosted chat model is still given (below that the step goes straight to Gemini).
_FALLBACK_RESERVE_SEC = 30.0
_MIN_CHAT_MODEL_TIMEOUT_SEC = 15.0


def _unsigned_function_call(part: Any) -> bool:
    return getattr(part, "function_call", None) is not None and not getattr(part, "thought_signature", None)


def _as_genai_part(part: Any) -> types.Part | None:
    if isinstance(part, types.Part):
        return part
    if getattr(part, "function_call", None) is not None:
        return types.Part(function_call=part.function_call)
    if getattr(part, "function_response", None) is not None:
        return types.Part(function_response=part.function_response)
    text = getattr(part, "text", None)
    return types.Part(text=text, thought=bool(getattr(part, "thought", False)) or None) if text else None


def _contents_for_gemini(contents: Any) -> Any:
    """`contents` as sent to Gemini: function calls without a thought_signature (made by the
    self-hosted chat model earlier in the turn) get the placeholder signature. Real Gemini
    signatures are kept; `contents` itself is not changed."""
    if isinstance(contents, str):
        return contents
    out = []
    for c in contents:
        parts = list(getattr(c, "parts", None) or [])
        if not any(_unsigned_function_call(p) for p in parts):
            out.append(c)
            continue
        new_parts: list[types.Part] = []
        for p in parts:
            if _unsigned_function_call(p):
                new_parts.append(types.Part(function_call=p.function_call, thought_signature=_PLACEHOLDER_THOUGHT_SIGNATURE))
            else:
                gp = _as_genai_part(p)
                if gp is not None:
                    new_parts.append(gp)
        out.append(types.Content(role=getattr(c, "role", None) or "model", parts=new_parts))
    return out


def _generate(model: str, contents: Any, config: Any, *, timeout: float | None = None) -> Any:
    """One chat model call: the self-hosted chat model (with a per-request timeout) or Gemini
    (with placeholder signatures on the self-hosted model's tool calls)."""
    client = client_for_chat_model(model, _client)
    if is_chat_openai_model(model):
        kwargs = {"timeout": timeout} if timeout else {}
        return client.models.generate_content(model=model, contents=contents, config=config, **kwargs)
    return client.models.generate_content(model=model, contents=_contents_for_gemini(contents), config=config)


def _usage_summary(resp: Any) -> dict[str, Any]:
    """Token counts (and server timings, for the self-hosted model) of one model response."""
    if resp is None:
        return {}
    usage = getattr(resp, "usage", None)
    if isinstance(usage, dict):
        return usage
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return {}
    out = {
        "prompt_tokens": getattr(meta, "prompt_token_count", None),
        "cached_tokens": getattr(meta, "cached_content_token_count", None),
        "output_tokens": getattr(meta, "candidates_token_count", None),
        "thought_tokens": getattr(meta, "thoughts_token_count", None),
    }
    return {k: v for k, v in out.items() if isinstance(v, int) and not isinstance(v, bool)}


def _log_model_call(hop: Any, model: str, started: float, resp: Any = None, error: Exception | None = None) -> None:
    ms = round((time.perf_counter() - started) * 1000)
    u = _usage_summary(resp) if error is None else {}
    server_ms = u.get("server_ms")
    # Wall time the server spent not working on this request: queueing or loading the model.
    wait_ms = max(0, ms - server_ms) if isinstance(server_ms, (int, float)) else None
    logger.info(
        "[coach] model_call hop=%s model=%s ok=%s ms=%s prompt_tokens=%s cached_tokens=%s output_tokens=%s "
        "thought_tokens=%s server_ms=%s wait_ms=%s%s",
        hop, model, error is None, ms, u.get("prompt_tokens"), u.get("cached_tokens"), u.get("output_tokens"),
        u.get("thought_tokens"), server_ms, wait_ms,
        f" error={type(error).__name__}: {str(error)[:300]}" if error is not None else "",
    )


def _chat_model_timeout(turn_deadline: float | None) -> float | None:
    """Timeout for the next self-hosted chat model request: CHAT_REQUEST_TIMEOUT_SEC, capped at
    what is left of the turn minus the Gemini reserve. None when too little is left."""
    cap = float(settings.CHAT_REQUEST_TIMEOUT_SEC)
    if turn_deadline is None:
        return cap
    left = turn_deadline - time.perf_counter() - _FALLBACK_RESERVE_SEC
    if left < _MIN_CHAT_MODEL_TIMEOUT_SEC:
        return None
    return min(cap, left)


def _wrap_up_after_tool_budget(
    contents: list[types.Content],
    system_instruction: str,
    candidates: list[str],
    turn_deadline: float | None = None,
) -> str:
    wrap = list(contents) + [types.Content(role="user", parts=[types.Part.from_text(text=_WRAP_UP_NOTE)])]
    config = types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.4)
    for model in candidates:
        timeout = None
        if is_chat_openai_model(model):
            timeout = _chat_model_timeout(turn_deadline)
            if timeout is None:
                if model != candidates[-1]:
                    continue
                timeout = float(settings.CHAT_REQUEST_TIMEOUT_SEC)
        started = time.perf_counter()
        try:
            gemini_quota.wait_for_slot(model, max_wait_sec=20.0)
            resp = _generate(model, wrap, config, timeout=timeout)
            _log_model_call("wrap_up", model, started, resp)
        except Exception as e:
            _log_model_call("wrap_up", model, started, error=e)
            logger.warning("[coach] wrap-up call failed model=%s: %r", model, e)
            continue
        text = _extract_athlete_message_from_text(_extract_non_thought_text_from_response(resp))
        if text.strip() and not _is_failed_extraction(text):
            return text
    return ""


# "I've scheduled / added / cleared / moved …", "… into your calendar", "synced to your app".
_PLAN_CHANGE_CLAIM_RE = re.compile(
    r"\b(i(?:'| ha)ve|i just|i)\s+(?:\w+\s+){0,6}?"
    r"(scheduled|added|cleared|populated|loaded|moved|swapped|replaced|updated|built|mapped out|put|deleted|"
    r"removed|logged|rescheduled|pushed|integrated|programmed|set up|locked in|uploaded|created)\b"
    r"|\b(synced|saved|added|scheduled|loaded|populated|pushed|integrated|locked in|uploaded)\s+(?:\w+\s+){0,3}?"
    r"(to|into|in|on)\s+(your\s+)?(app\s+)?(calendar|plan|app|training plan)\b"
    r"|\b(now\s+)?live (on|in) your\b"
    r"|\b(fully|now)\s+(populated|scheduled|loaded|locked in)\b"
    r"|\bcheck your (calendar|plan)\b",
    re.IGNORECASE,
)

# A claim needs one of these to have actually run (a clear alone doesn't fill a calendar).
_CALENDAR_CHANGE_TOOLS = frozenset({
    "schedule_workout", "schedule_workouts", "update_planned_workout", "delete_planned_workout",
    "clear_training_plans", "import_plan",
})
_CALENDAR_NOW_MAX_DAYS = 62
_CALENDAR_NOW_MAX_LINES = 90


def _dates_touched(args: dict[str, Any], result: Any) -> list[str]:
    out: list[str] = []
    for k in ("date", "start_date", "end_date", "planned_date", "new_date"):
        v = args.get(k)
        if isinstance(v, str) and len(v) >= 10:
            out.append(v[:10])
    for w in args.get("workouts") or []:
        if isinstance(w, dict) and isinstance(w.get("date"), str):
            out.append(w["date"][:10])
    if isinstance(result, dict):
        for k in ("planned_date", "start_date", "end_date"):
            v = result.get(k)
            if isinstance(v, str) and len(v) >= 10:
                out.append(v[:10])
    return out


def _calendar_now_note(db: Any, athlete_id: str, dates: list[str]) -> str | None:
    """What is actually saved for the days just changed: by weekday, then by date. The model
    describes the plan from this instead of from its own idea of what it scheduled (prod:
    'strength on Mon/Wed/Thu' when Wednesday never had one)."""
    try:
        ds = sorted({date.fromisoformat(d) for d in dates})
    except ValueError:
        return None
    if not ds:
        return None
    start = ds[0]
    end = min(ds[-1], start + timedelta(days=_CALENDAR_NOW_MAX_DAYS - 1))
    try:
        rows = (
            db.table("training_plans")
            .select("planned_date,title,sport,duration_min,status")
            .eq("athlete_id", athlete_id)
            .gte("planned_date", start.isoformat())
            .lte("planned_date", end.isoformat())
            .order("planned_date")
            .execute()
        ).data or []
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    by_weekday: dict[str, dict[str, int]] = {}
    lines: list[str] = []
    for r in rows:
        try:
            d = date.fromisoformat(str(r.get("planned_date"))[:10])
        except ValueError:
            continue
        title = str(r.get("title") or "Session")
        wd = d.strftime("%A")
        by_weekday.setdefault(wd, {})
        by_weekday[wd][title] = by_weekday[wd].get(title, 0) + 1
        if len(lines) < _CALENDAR_NOW_MAX_LINES:
            lines.append(f"{d:%a} {d.isoformat()}: {title} ({r.get('sport')}, {r.get('duration_min')} min)")
    order = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    pattern = [
        f"{wd}: " + "; ".join(f"{t} x{n}" for t, n in sorted(by_weekday[wd].items(), key=lambda x: -x[1]))
        if wd in by_weekday
        else f"{wd}: nothing"
        for wd in order
    ]
    more = f"\n… {len(rows) - len(lines)} more" if len(rows) > len(lines) else ""
    return (
        f"[CALENDAR NOW: what is actually saved for {start.isoformat()} to {end.isoformat()} after your changes "
        f"({len(rows)} sessions). When you tell the athlete what the plan looks like, describe only this; "
        "never mention a session or weekday that isn't listed. If it doesn't match what they asked for, fix it "
        "with tools before replying.]\n"
        "By weekday:\n" + "\n".join(pattern) + "\n\nBy date:\n" + "\n".join(lines) + more
    )


_PLAN_WRITE_TOOLS = frozenset({
    "schedule_workout", "schedule_workouts", "update_planned_workout", "delete_planned_workout",
    "log_workout", "update_workout", "import_plan",
})

# The athlete asked for sessions to go (clear / delete / start over): clears run as asked.
_EXPLICIT_CLEAR_RE = re.compile(
    r"\b(clear|delete|remove|wipe|reset|erase|start (?:over|fresh)|replace|scrap|get rid of)\b", re.IGNORECASE
)

_UNSAVED_CLAIM_NOTE = (
    "[SYSTEM] Your reply says you changed the athlete's calendar or plan, but you did not call "
    "any tool this turn, so NOTHING was saved. If the athlete asked for that change, call the tools "
    "now to actually make it (schedule_workouts with every session; to replace a range, call "
    "clear_training_plans first) and reply with what was really saved. If they didn't, "
    "rewrite your reply so it doesn't say anything was changed."
)
_UNSAVED_CLAIM_DISCLAIMER = (
    "_Note: nothing was actually saved to your calendar this time. Ask me again and I'll schedule it._"
)


def _defer_clear(args: dict[str, Any], pending: list[tuple[str, str]]) -> dict[str, Any]:
    start = str(args.get("start_date") or "")[:10]
    end = str(args.get("end_date") or "")[:10]
    try:
        if date.fromisoformat(end) < date.fromisoformat(start):
            return {"error": "end_date must be >= start_date"}
    except ValueError:
        return {"error": "start_date and end_date must be YYYY-MM-DD"}
    pending.append((start, end))
    return {
        "status": "deferred",
        "note": (
            "Nothing deleted yet. When you schedule sessions in this range, the existing sessions on "
            "those same days are replaced; days you don't schedule keep their sessions. To add "
            "sessions, just schedule them."
        ),
    }


def _plan_sport(raw: Any) -> str:
    s = str(raw or "other").strip().lower()
    return {
        "cycling": "bike", "ride": "bike", "biking": "bike", "running": "run", "rowing": "row", "erg": "row",
        "gym": "strength", "weights": "strength", "lifting": "strength", "yoga": "mobility", "swimming": "swim",
    }.get(s, s)


def _apply_pending_clears(db: Any, athlete_id: str, args: dict[str, Any], name: str, pending: list[tuple[str, str]]) -> int:
    """Like-for-like replacement within a deferred clear range: on each day about to get a new
    session, delete only the not-done sessions of the same sport. Rescheduling Tuesday's
    strength replaces the old strength session but leaves Tuesday's rowing alone."""
    items = args.get("workouts") if name == "schedule_workouts" else [args]
    wanted: dict[str, set[str]] = {}
    for i in items or []:
        if not isinstance(i, dict):
            continue
        d = str(i.get("date") or "")[:10]
        if d and any(s <= d <= e for s, e in pending):
            wanted.setdefault(d, set()).add(_plan_sport(i.get("sport")))
    if not wanted:
        return 0
    existing = (
        db.table("training_plans")
        .select("id,planned_date,sport")
        .eq("athlete_id", athlete_id)
        .in_("status", ["planned", "modified"])
        .in_("planned_date", sorted(wanted))
        .execute()
    ).data or []
    if not isinstance(existing, list):
        return 0
    ids = [
        r["id"]
        for r in existing
        if isinstance(r, dict) and _plan_sport(r.get("sport")) in wanted.get(str(r.get("planned_date"))[:10], set())
    ]
    if not ids:
        return 0
    res = db.table("training_plans").delete().eq("athlete_id", athlete_id).in_("id", ids).execute()
    return len(res.data or [])


_PLAN_TALK_RE = re.compile(
    r"\b(plan|calendar|schedul\w*|session|workout|week|weeks|month|months|today|tomorrow|monday|tuesday|"
    r"wednesday|thursday|friday|saturday|sunday|missing|fix|move|swap|add|remove|delete|clear|replace|"
    r"strength|tank|cat ?[12]|cross.?train|speed|erg|ride|run|swim)\b",
    re.IGNORECASE,
)


def _calendar_before_note(db: Any, athlete_id: str, calendar: dict[str, Any], message: str) -> str | None:
    """What is already on the calendar, from the start of this week through four weeks out, so
    the model edits what is there instead of guessing (prod: 'fix this week' rebuilt it blind)."""
    if not _PLAN_TALK_RE.search(message or ""):
        return None
    try:
        today = date.fromisoformat(str(calendar.get("current_local_date"))[:10])
    except ValueError:
        return None
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)  # Sunday
    note = _calendar_now_note(db, athlete_id, [week_start.isoformat(), (week_start + timedelta(days=34)).isoformat()])
    if not note:
        return None
    return note.replace(
        "[CALENDAR NOW: what is actually saved for",
        "[CALENDAR BEFORE THIS MESSAGE: what is already saved for",
    ).replace(
        "after your changes", "before you change anything"
    ).replace(
        "When you tell the athlete what the plan looks like, describe only this; never mention a session or "
        "weekday that isn't listed. If it doesn't match what they asked for, fix it with tools before replying.",
        "Read this before changing anything: keep what is already right, change only what the athlete asked "
        "for, and never re-create sessions that are already here. Use list_planned_workouts for other dates.",
    )


def _claims_plan_change(text: str) -> bool:
    return bool(_PLAN_CHANGE_CLAIM_RE.search(text or ""))


_MUTATING_TOOL_NAMES = frozenset({
    "import_plan",
    "schedule_workout",
    "schedule_workouts",
    "log_workout",
    "update_workout",
    "log_biometrics",
    "update_profile",
    "update_planned_workout",
    "delete_planned_workout",
    "clear_training_plans",
    "save_memory",
    "update_memory",
})


def get_coach_response_agentic(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
    max_tool_hops: int = 15,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    tools_enabled: bool = True,
) -> tuple[str, list[dict[str, str]]]:
    """
    Non-streaming coach reply with manual Gemini function calling (tool loop); see
    _get_coach_response_agentic. Logs one summary line per turn.
    """
    stats: dict[str, Any] = {"hops": 0, "models": [], "fallback": None}
    t0 = time.perf_counter()
    outcome = "error"
    try:
        reply, sources = _get_coach_response_agentic(
            athlete_id, message, current_tss=current_tss, db=db, conversation_id=conversation_id,
            model_name=model_name, timezone_offset_min=timezone_offset_min, max_tool_hops=max_tool_hops,
            progress_callback=progress_callback, tools_enabled=tools_enabled, _stats=stats,
        )
        outcome = "failure_reply" if reply in COACH_FAILURE_REPLIES else "ok"
        return reply, sources
    finally:
        logger.info(
            "[coach] turn ms=%s hops=%s models=%s fallback=%s outcome=%s",
            round((time.perf_counter() - t0) * 1000), stats["hops"], ",".join(stats["models"]) or "-",
            stats["fallback"] or "-", outcome,
        )


def _get_coach_response_agentic(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
    max_tool_hops: int = 15,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    tools_enabled: bool = True,
    _stats: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """
    Non-streaming coach reply with manual Gemini function calling (tool loop).
    tools_enabled=False skips every tool: one model call, for callers that already put the
    data in the prompt (each extra tool hop is a full model round trip).
    Returns (athlete-facing message, web search citation sources when present).
    """
    system_instruction = load_coach_instructions()
    coach_t0 = time.perf_counter()
    stats = _stats if _stats is not None else {"hops": 0, "models": [], "fallback": None}
    if db:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            context_block = asyncio.run(
                _assemble_agentic_context_async(
                    db,
                    athlete_id,
                    message,
                    current_tss=current_tss,
                    conversation_id=conversation_id,
                    timezone_offset_min=timezone_offset_min,
                )
            )
        else:
            raise RuntimeError(
                "get_coach_response_agentic() was called from an async context. "
                "Use get_coach_response_agentic_async() instead."
            )
        logger.info(
            "[perf] coach_context duration_ms=%s rag_skipped=%s",
            round((time.perf_counter() - coach_t0) * 1000, 1),
            should_skip_rag_for_message(message),
        )
        _coach_progress(progress_callback, "context_ready")
    else:
        context_block = (
            f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\n"
            f"Most recent workout TSS: {current_tss}\n[END CONTEXT]"
        )
    system_with_ctx = (
        f"{system_instruction}\n\n{context_block}\n\n"
        "Calendar rule: for all relative dates, including today, tomorrow, named weekdays, this week, and next week, "
        "use the athlete-local current_local_date, current_local_weekday, tomorrow_date, tomorrow_weekday, and upcoming_weekdays from SYSTEM CONTEXT. "
        "For follow-up clarifications, preserve the previously discussed workout date unless the athlete clearly changes it. "
        "Do not infer dates from UTC, server time, or model pretraining."
    )

    if not db:
        final_prompt = f"{system_with_ctx}\n\nAthlete Message: {message}"
        effective_model = model_name or settings.GEMINI_MODEL
        gemini_quota.wait_for_slot(effective_model, max_wait_sec=15.0)
        response = _client.models.generate_content(
            model=effective_model,
            contents=final_prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=False),
                temperature=0.35,
            ),
        )
        return (
            _extract_athlete_message_from_model_output(response),
            _extract_grounding_sources(response),
        )

    history = (
        _load_conversation_history(db, athlete_id, conversation_id, limit=24)
        if conversation_id
        else []
    )
    calendar = _athlete_local_calendar(db, athlete_id, timezone_offset_min=timezone_offset_min)
    contents = _history_to_gemini_contents(history, image_parts=lambda urls: _load_image_parts(db, urls))
    last_user = next((r for r in reversed(history) if r.get("role") == "user"), None)
    history_has_images = bool(last_user and last_user.get("image_urls"))
    # Always append the current user message (history alone is not sufficient).
    before = _calendar_before_note(db, athlete_id, calendar, message) if (tools_enabled and db is not None) else None
    if before:
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=before)]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=_calendar_preface(message, calendar))]))
    # If there was no history, `contents` is now a 1-item list with the current message.

    # (There used to be a keyword "backstop" here that deleted a whole week of plans
    # whenever a message mentioned delete/remove/clear + plan + this/next week, before
    # the model saw it, so "don't remove anything from my plan next week" wiped it.
    # Clearing is now only ever the model's explicit, bounded clear_training_plans call.)

    # CHAT_LLM_PROVIDER=openai: the chat runs on the self-hosted CHAT_MODEL, and the Gemini
    # fallback model below takes over if it fails.
    primary_model = settings.CHAT_MODEL.strip() if chat_uses_openai() else (model_name or settings.GEMINI_MODEL)
    fallback_model = (getattr(settings, "GEMINI_FALLBACK_MODEL", "") or "").strip()
    candidates: list[str] = [primary_model]
    if fallback_model and fallback_model not in candidates:
        candidates.append(fallback_model)

    # Only use ThinkingConfig for models that specifically support it
    is_thinking_model = "thinking" in primary_model.lower()
    
    # The prompt tells the model to call internal_scratchpad first; when that tool is dropped
    # (native-thinking models) say so, so it doesn't try to call a tool that isn't there.
    system_for_models = system_with_ctx
    if coach_tools.scratchpad_dropped(candidates):
        system_for_models += SCRATCHPAD_UNAVAILABLE_NOTE
    if tools_enabled:
        config = types.GenerateContentConfig(
            system_instruction=system_for_models,
            tools=coach_tools.tools_for_models(candidates),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(include_server_side_tool_invocations=True),
            temperature=0.4,
        )
    else:
        config = types.GenerateContentConfig(system_instruction=system_for_models, temperature=0.4)
    # After a "you said you changed the calendar but didn't" nudge, the next call must call a
    # function (mode ANY) instead of answering in text again. Function tools only: ANY can't
    # be combined with server-side search.
    forced_config = None
    if tools_enabled:
        fn_tools = [t for t in (config.tools or []) if getattr(t, "function_declarations", None)]
        forced_config = types.GenerateContentConfig(
            system_instruction=system_for_models,
            tools=fn_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            temperature=0.4,
        )
    force_tools_next = False
    if is_thinking_model:
        config.thinking_config = types.ThinkingConfig(include_thoughts=False)

    last_response = None
    planned_dates_from_tools: list[str] = []
    # Tools that change data and actually ran this turn (any result, including errors).
    mutations_run: list[str] = []
    claim_nudged = False
    # clear_training_plans the athlete didn't ask for: held until sessions are scheduled, then
    # applied only to the days that get new sessions (so a partial reschedule can't wipe a plan).
    explicit_clear = bool(_EXPLICIT_CLEAR_RE.search(message or ""))
    pending_clears: list[tuple[str, str]] = []
    last_tool_names: list[str] = []
    max_hops = _agentic_max_tool_hops(message, has_images=history_has_images)
    self_hosted_failed = False
    # The self-hosted chat model gets what is left of this budget (minus a Gemini reserve);
    # after that the turn continues on Gemini.
    turn_deadline = coach_t0 + float(settings.CHAT_TURN_DEADLINE_SEC) if chat_uses_openai() else None
    for _hop in range(max_hops):
        stats["hops"] = _hop + 1
        hop_t0 = time.perf_counter()
        _coach_progress(progress_callback, "thinking", hop=_hop)
        _hop_error: Exception | None = None
        hop_candidates = [m for m in candidates if not (self_hosted_failed and is_chat_openai_model(m))]
        for _model_idx, effective_model in enumerate(hop_candidates):
            _hop_error = None
            _transient = False
            chat_timeout = None
            if is_chat_openai_model(effective_model):
                chat_timeout = _chat_model_timeout(turn_deadline)
                if chat_timeout is None:
                    if _model_idx < len(hop_candidates) - 1:
                        logger.warning(
                            "[coach] turn time limit: %.0fs used, rest of the turn on %s",
                            time.perf_counter() - coach_t0, hop_candidates[_model_idx + 1],
                        )
                        self_hosted_failed = True
                        stats["fallback"] = stats["fallback"] or "turn_time_limit"
                        continue
                    chat_timeout = float(settings.CHAT_REQUEST_TIMEOUT_SEC)
            # Only the last candidate is retried: a failing call can itself take 10+ s, so when
            # a fallback model exists it is tried after one failure instead of after 3 retries.
            max_attempts = 3 if _model_idx == len(hop_candidates) - 1 else 1
            for _attempt in range(max_attempts):
                call_t0 = time.perf_counter()
                try:
                    # Blocks (bounded) rather than firing and getting a 429 —
                    # the free-tier RPM budget for the Gemma models here is
                    # tight enough (~30/min) that a single multi-hop turn
                    # plus its title/memory background calls can burn
                    # through it on their own. A GeminiQuotaExceededError
                    # here contains "quota exceeded", so it flows straight
                    # into the existing _should_fallback_chat_model() check
                    # below like any other overload signal.
                    gemini_quota.wait_for_slot(effective_model, max_wait_sec=20.0)
                    call_t0 = time.perf_counter()
                    last_response = _generate(
                        effective_model,
                        contents,
                        forced_config if (force_tools_next and forced_config is not None) else config,
                        timeout=chat_timeout,
                    )
                    _log_model_call(_hop, effective_model, call_t0, last_response)
                    stats["models"].append(effective_model)
                    _hop_error = None
                    break
                except Exception as e:
                    _log_model_call(_hop, effective_model, call_t0, error=e)
                    _hop_error = e
                    err_str = str(e)
                    # Catch broad transient errors and connection-level failures
                    is_transient = any(
                        k in err_str
                        for k in (
                            "500", "503", "INTERNAL", "overloaded", "Server disconnected",
                            "RemoteProtocolError", "EOF",
                            # Rate-limit/timeout signatures — previously excluded, so a 429
                            # or a slow tool-heavy hop skipped straight to the single-attempt
                            # failure path below instead of getting a backoff-and-retry.
                            "429", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "timeout", "Timeout",
                            # httpx.ReadTimeout's message is "The read operation timed out".
                            "timed out", "504",
                        )
                    ) or isinstance(e, (httpx.TimeoutException, TimeoutError))
                    _transient = is_transient
                    if _attempt < max_attempts - 1 and is_transient:
                        wait = 1.5 * (_attempt + 1)
                        logger.warning(
                            "[coach] transient error model=%s hop=%s attempt=%s: %s; retrying in %ss",
                            effective_model, _hop, _attempt + 1, e, wait,
                        )
                        time.sleep(wait)
                        continue
                    break

            # Success with this model.
            if _hop_error is None:
                break

            # If this model looks overloaded/unavailable (or hit any transient error), try the
            # next configured fallback model.
            # Any failure of the self-hosted chat model falls back (it has no "overloaded" codes).
            if _model_idx < len(hop_candidates) - 1 and (
                _transient
                or _should_fallback_chat_model(str(_hop_error))
                or is_chat_openai_model(effective_model)
            ):
                logger.warning(
                    "[coach] model=%s failed (hop %s), trying fallback model=%s",
                    effective_model, _hop, hop_candidates[_model_idx + 1],
                )
                stats["fallback"] = stats["fallback"] or type(_hop_error).__name__
                if is_chat_openai_model(effective_model):
                    # Stay on Gemini for the rest of this turn rather than waiting on the
                    # self-hosted model again at every tool hop.
                    logger.warning("[coach] self-hosted chat model failed, using %s for this turn: %r",
                                   hop_candidates[_model_idx + 1], _hop_error)
                    self_hosted_failed = True
                continue

            # Otherwise don't keep iterating candidates.
            break

        force_tools_next = False
        logger.info(
            "[perf] coach_hop hop=%s duration_ms=%s",
            _hop,
            round((time.perf_counter() - hop_t0) * 1000, 1),
        )

        if _hop_error is not None:
            logger.error("[coach] generate_content failed after retries (hop %s): %r", _hop, _hop_error)
            # last_tool_names only sees model-issued function calls; the
            # backward scan also catches the deterministic pre-loop
            # backstops (e.g. clear_training_plans below) and skips past a
            # calendar-reminder turn appended after the real tool result —
            # see _tool_names_from_last_function_response's docstring.
            tool_names = _tool_names_from_last_function_response(contents) or last_tool_names
            if tool_names:
                # The call that was meant to turn tool results into a final
                # answer failed — this used to unconditionally claim "I have
                # successfully processed your data and updated your status",
                # which is actively false for a read-only question (nothing
                # was updated) and gives no signal that anything went wrong.
                # Only claim a change happened if a mutating tool actually
                # ran in the hop right before this failure.
                if any(name in _MUTATING_TOOL_NAMES for name in tool_names):
                    return (COACH_PARTIAL_ERROR_REPLY, [])
                return (COACH_ERROR_REPLY, [])
            raise _hop_error

        if not last_response.candidates:
            break
        cand = last_response.candidates[0]
        if not cand.content or not cand.content.parts:
            break

        parts = list(cand.content.parts)
        fcs = [getattr(p, "function_call", None) for p in parts if getattr(p, "function_call", None)]
        has_tool_results = any(
            getattr(p, "function_response", None) is not None for p in parts
        )

        if fcs:
            # Carry each part's thought_signature over: Gemini 3+ attaches one to the model's
            # function_call parts and rejects the follow-up request with a 400 if it is missing.
            fc_parts: list[types.Part] = [
                types.Part(
                    function_call=p.function_call,
                    thought_signature=getattr(p, "thought_signature", None),
                )
                for p in parts
                if getattr(p, "function_call", None)
            ]
            if not fc_parts:
                break
            last_tool_names = [fc.name for fc in fcs if fc is not None and fc.name]
            contents.append(types.Content(role="model", parts=fc_parts))

            fr_parts: list[types.Part] = []
            hop_dates: list[str] = []
            for fc in fcs:
                if fc is None or not fc.name:
                    continue
                name = fc.name
                if name in _MUTATING_TOOL_NAMES:
                    mutations_run.append(name)
                _coach_progress(progress_callback, "tool", tool=name)
                args = coach_tools.parse_function_args(fc)
                args = _normalize_relative_tool_dates(name, args, message=message, calendar=calendar)
                handler = coach_tools.TOOL_HANDLERS.get(name)
                tool_t0 = time.perf_counter()
                try:
                    if name == "clear_training_plans" and not explicit_clear:
                        result = _defer_clear(args, pending_clears)
                    elif name == "import_plan":
                        result = plan_import.run_import(
                            args,
                            athlete_id=athlete_id,
                            db=db,
                            history=history,
                            current_message=message,
                            load_images=lambda urls: _load_image_parts(db, urls),
                        )
                    else:
                        if name in ("schedule_workout", "schedule_workouts") and pending_clears:
                            _apply_pending_clears(db, athlete_id, args, name, pending_clears)
                        result = handler(args, athlete_id, db) if handler else {"error": f"unknown_tool:{name}"}
                except Exception as e:
                    result = {"error": str(e)}
                if name == "schedule_workout" and isinstance(result, dict):
                    planned_date = result.get("planned_date")
                    workout_strict = result.get("workout_strict")
                    if not isinstance(planned_date, str) and isinstance(workout_strict, dict):
                        planned_date = workout_strict.get("date")
                    if isinstance(planned_date, str) and planned_date:
                        planned_dates_from_tools.append(planned_date[:10])
                if name == "schedule_workouts" and isinstance(result, dict):
                    for item in result.get("scheduled") or []:
                        d = item.get("date") if isinstance(item, dict) else None
                        if isinstance(d, str) and d:
                            planned_dates_from_tools.append(d[:10])
                # Name, time and outcome only: arguments and results carry the athlete's data.
                logger.info(
                    "[coach] tool hop=%s name=%s ms=%s ok=%s",
                    _hop, name, round((time.perf_counter() - tool_t0) * 1000),
                    not (isinstance(result, dict) and result.get("error")),
                )
                if name in _CALENDAR_CHANGE_TOOLS:
                    hop_dates.extend(_dates_touched(args, result))
                # Durations also as text ("90 min", "7h 29m") so replies never say "449 minutes".
                fr_parts.append(types.Part.from_function_response(name=name, response=with_duration_text(result)))
            if fr_parts:
                contents.append(types.Content(role="user", parts=fr_parts))
                if hop_dates:
                    note = _calendar_now_note(db, athlete_id, hop_dates)
                    if note:
                        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=note)]))
                reminder = _calendar_tool_result_reminder(planned_dates_from_tools, calendar)
                if reminder:
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=reminder)]))
            continue

        if has_tool_results:
            contents.append(cand.content)
            continue

        joined = _extract_non_thought_text_from_response(last_response)
        if joined.strip():
            final_text = _extract_athlete_message_from_text(joined)
            if not _is_failed_extraction(final_text):
                # The reply says the calendar/plan was changed, but no write tool ran this turn:
                # nothing was saved. Push back once so the model makes the calls for real.
                wrote = any(n in _PLAN_WRITE_TOOLS for n in mutations_run)
                if tools_enabled and not wrote and _claims_plan_change(final_text):
                    if not claim_nudged and _hop < max_hops - 1:
                        claim_nudged = True
                        logger.warning("[coach] reply claimed a plan change without tool calls; nudging")
                        contents.append(cand.content)
                        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=_UNSAVED_CLAIM_NOTE)]))
                        force_tools_next = True
                        continue
                    logger.warning("[coach] reply still claims a plan change without tool calls")
                    final_text = f"{final_text}\n\n{_UNSAVED_CLAIM_DISCLAIMER}"
                return (
                    _correct_relative_date_language(final_text, planned_dates_from_tools, calendar),
                    _extract_grounding_sources(last_response),
                )
        break

    fallback = _extract_non_thought_text_from_response(last_response) if last_response else ""
    final = _extract_athlete_message_from_text(fallback)
    if _is_failed_extraction(final):
        final = ""
    if not final and last_response is not None and tools_enabled:
        # Ran out of tool rounds mid-task (e.g. importing a long plan). The tool results
        # are already in `contents`; ask once more with tools off so the athlete gets an
        # honest summary of what was done and what is left, not a generic failure.
        final = _wrap_up_after_tool_budget(
            contents,
            system_for_models,
            [m for m in candidates if not (self_hosted_failed and is_chat_openai_model(m))],
            turn_deadline=turn_deadline,
        )
    if (
        final
        and tools_enabled
        and not any(n in _PLAN_WRITE_TOOLS for n in mutations_run)
        and _claims_plan_change(final)
    ):
        logger.warning("[coach] fallback reply claims a plan change without tool calls")
        final = f"{final}\n\n{_UNSAVED_CLAIM_DISCLAIMER}"
    final = _correct_relative_date_language(final, planned_dates_from_tools, calendar)
    grounding = _extract_grounding_sources(last_response) if last_response else []
    if not final and last_response is not None:
        part_kinds = []
        try:
            cand = (last_response.candidates or [None])[0]
            for p in getattr(getattr(cand, "content", None), "parts", None) or []:
                if getattr(p, "function_call", None):
                    part_kinds.append("function_call")
                elif getattr(p, "function_response", None):
                    part_kinds.append("function_response")
                elif getattr(p, "thought", False):
                    part_kinds.append("thought")
                elif getattr(p, "text", None):
                    part_kinds.append("text")
                else:
                    part_kinds.append(type(p).__name__)
        except Exception:
            part_kinds = ["unknown"]
        logger.warning(
            "[coach] empty athlete reply after %s hop(s); part_kinds=%s",
            _hop + 1 if last_response else 0,
            part_kinds,
        )
    return (final or COACH_INCOMPLETE_REPLY, grounding)


async def get_coach_response_agentic_async(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
    max_tool_hops: int = 15,
) -> tuple[str, list[dict[str, str]]]:
    """
    Async-safe wrapper for use from `async def` code.

    The Gemini SDK calls (and the agentic tool-loop) are synchronous; this helper runs
    the full agentic implementation in a worker thread so it retains tool calling,
    retries/fallbacks, and max_tool_hops behavior.
    """
    return await asyncio.to_thread(
        get_coach_response_agentic,
        athlete_id=athlete_id,
        message=message,
        current_tss=current_tss,
        db=db,
        conversation_id=conversation_id,
        model_name=model_name,
        timezone_offset_min=timezone_offset_min,
        max_tool_hops=max_tool_hops,
    )


_BULK_PLAN_HINTS = (
    "[attached document",
    "training plan",
    "full plan",
    "whole plan",
    "into the plan",
    "into my plan",
    "into the app",
    "import",
    "weeks",
    "months",
    "month",
    "photo",
    "picture",
    "screenshot",
)


def _agentic_max_tool_hops(message: str, has_images: bool = False) -> int:
    msg_l = (message or "").lower()
    # Importing or building a multi-week plan: clear + several batches + checks.
    if has_images or any(h in msg_l for h in _BULK_PLAN_HINTS):
        return 14
    if any(
        w in msg_l
        for w in (
            "schedule",
            "plan my",
            "build my",
            "clear my",
            "delete my",
            "this week",
            "next week",
            "training week",
        )
    ):
        return 8
    if should_skip_rag_for_message(message):
        return 3
    return 5


async def _assemble_agentic_context_async(
    db: Client,
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
    timezone_offset_min: int | None = None,
) -> str:
    """Parallel DB reads + optional RAG for agentic coach."""
    use_rag = not should_skip_rag_for_message(message)

    async def load_memories() -> list[dict]:
        if not use_rag:
            return []
        return await asyncio.to_thread(
            retrieve_relevant_memories, athlete_id, message, db, 5
        )

    async def load_hist() -> list[dict]:
        if not conversation_id:
            return []
        return await asyncio.to_thread(
            _load_conversation_history, db, athlete_id, conversation_id, 24
        )

    training, bio, profile, memories, hist_rows = await asyncio.gather(
        asyncio.to_thread(_summarize_training_load, db, athlete_id, current_tss),
        asyncio.to_thread(_summarize_biometrics, db, athlete_id),
        asyncio.to_thread(_summarize_athlete_profile, db, athlete_id),
        load_memories(),
        load_hist(),
    )
    offset = coerce_timezone_offset_min(
        profile.get("timezone_offset_min") if timezone_offset_min is None else timezone_offset_min
    )
    calendar = _calendar_context_for_offset(offset)
    today = calendar["current_local_date"]
    profile = {**profile, "timezone_offset_min": offset}
    ctx: dict = {
        "date": today,
        **calendar,
        "timezone_offset_min": offset,
        "calendar_rules": {
            "today": "Resolve today from current_local_date in the athlete's timezone.",
            "tomorrow": "Resolve tomorrow from tomorrow_date in the athlete's timezone.",
            "named_weekdays": "Resolve weekday names from upcoming_weekdays.",
            "followups": "If the athlete clarifies a plan with words like this, that, it, or all, keep the previously discussed workout date unless they clearly change it.",
            "memory_dates": MEMORY_CONTEXT_RULE,
        },
        "athlete_id": athlete_id,
        "training_load": training,
        "biometrics": bio,
        "athlete_profile": profile,
    }
    if memories:
        ctx["memories"] = memories_for_context(memories, today)
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": hist_rows,
        }
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(with_duration_text(ctx), ensure_ascii=False) + "\n[END CONTEXT]"


async def _build_system_context_string_async(
    db: Client,
    athlete_id: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
    query: str | None = None,
    timezone_offset_min: int | None = None,
) -> str:
    """
    Same payload as _build_system_context, but DB reads run in parallel to cut
    time-to-first-token on /v1/coach/stream (four sequential round-trips → one wait).
    """
    async def load_hist() -> list[dict]:
        if not conversation_id:
            return []
        return await asyncio.to_thread(
            _load_conversation_history, db, athlete_id, conversation_id, 24
        )

    async def load_memories() -> list[dict]:
        if not query:
            return []
        return await asyncio.to_thread(retrieve_relevant_memories, athlete_id, query, db, 5)

    async def load_recent_workouts() -> list[dict]:
        return await asyncio.to_thread(recent_workouts_teaser, db, athlete_id, 2)

    training, bio, profile, hist_rows, memories, recent_workouts = await asyncio.gather(
        asyncio.to_thread(_summarize_training_load, db, athlete_id, current_tss),
        asyncio.to_thread(_summarize_biometrics, db, athlete_id),
        asyncio.to_thread(_summarize_athlete_profile, db, athlete_id),
        load_hist(),
        load_memories(),
        load_recent_workouts(),
    )
    offset = coerce_timezone_offset_min(
        profile.get("timezone_offset_min") if timezone_offset_min is None else timezone_offset_min
    )
    calendar = _calendar_context_for_offset(offset)
    today = calendar["current_local_date"]
    profile = {**profile, "timezone_offset_min": offset}
    ctx: dict = {
        "date": today,
        **calendar,
        "timezone_offset_min": offset,
        "calendar_rules": {
            "today": "Resolve today from current_local_date in the athlete's timezone.",
            "tomorrow": "Resolve tomorrow from tomorrow_date in the athlete's timezone.",
            "named_weekdays": "Resolve weekday names from upcoming_weekdays.",
            "followups": "If the athlete clarifies a plan with words like this, that, it, or all, keep the previously discussed workout date unless they clearly change it.",
            "memory_dates": MEMORY_CONTEXT_RULE,
        },
        "athlete_id": athlete_id,
        "training_load": training,
        "biometrics": bio,
        "athlete_profile": profile,
    }
    if memories:
        ctx["memories"] = memories_for_context(memories, today)
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": hist_rows,
        }
    if recent_workouts:
        ctx["recent_workouts"] = recent_workouts
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(with_duration_text(ctx), ensure_ascii=False) + "\n[END CONTEXT]"


def get_coach_response(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    tools_enabled: bool = True,
) -> tuple[str, list[dict[str, str]]]:
    return get_coach_response_agentic(
        athlete_id=athlete_id,
        message=message,
        current_tss=current_tss,
        db=db,
        conversation_id=conversation_id,
        model_name=model_name,
        timezone_offset_min=timezone_offset_min,
        progress_callback=progress_callback,
        tools_enabled=tools_enabled,
    )

async def get_coach_response_stream(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    timezone_offset_min: int | None = None,
):
    system_instruction = load_coach_instructions()
    if db:
        context_block = await _build_system_context_string_async(
            db,
            athlete_id,
            current_tss=current_tss,
            conversation_id=conversation_id,
            timezone_offset_min=timezone_offset_min,
        )
    else:
        context_block = (
            f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
        )
    final_prompt = (
        f"{system_instruction}\n\n{context_block}\n\n"
        "Calendar rule: for all relative dates, including today, tomorrow, named weekdays, this week, and next week, "
        "use the athlete-local current_local_date, current_local_weekday, tomorrow_date, tomorrow_weekday, and upcoming_weekdays from SYSTEM CONTEXT. "
        "For follow-up clarifications, preserve the previously discussed workout date unless the athlete clearly changes it. "
        "Do not infer dates from UTC, server time, or model pretraining.\n\n"
        f"Athlete Message: {message}"
    )
    effective_model = (model_name or settings.GEMINI_MODEL)
    is_thinking_model = "thinking" in effective_model.lower()
    
    config = types.GenerateContentConfig(
        temperature=0.35,
    )
    if is_thinking_model:
        config.thinking_config = types.ThinkingConfig(include_thoughts=False)

    collected: list[str] = []
    for chunk in _client.models.generate_content_stream(
        model=effective_model,
        contents=final_prompt,
        config=config,
    ):
        t = _extract_non_thought_text_from_response(chunk, allow_text_fallback=False)
        if t:
            collected.append(t)
    full_text = "".join(collected)
    athlete_msg = _extract_athlete_message_from_text(full_text)
    if athlete_msg:
        chunk_size = 600
        for i in range(0, len(athlete_msg), chunk_size):
            yield athlete_msg[i : i + chunk_size]


_TITLE_SYSTEM = """You label coaching chat threads for a mobile sidebar.
Output exactly one short title: maximum 8 words, no quotation marks, no trailing punctuation, no emojis.
Describe the concrete training topic (race, CTL/TSB, recovery, intervals, nutrition, etc.), not meta phrases like "Chat" or "Discussion"."""


def _format_transcript_for_title(rows: list[dict], max_turns: int = 16, max_chars: int = 520) -> str:
    lines: list[str] = []
    for r in rows[-max_turns:]:
        role = (r.get("role") or "").strip()
        content = (r.get("content") or "").strip()
        content = re.sub(r"\s+", " ", content)
        if len(content) > max_chars:
            content = content[: max_chars - 1] + "…"
        label = "Athlete" if role == "user" else "Coach"
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _sanitize_generated_title(raw: str) -> str:
    t = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    t = t.strip(" \t\"'“”`•-—:")
    t = re.sub(r"^title:\s*", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 72:
        t = t[:72].rsplit(" ", 1)[0] if " " in t[:72] else t[:72]
    return t[:60]


def _fallback_title_from_history(rows: list[dict]) -> str:
    for r in reversed(rows):
        if (r.get("role") or "").strip() != "user":
            continue
        content = (r.get("content") or "").strip()
        if not content:
            continue
        base = " ".join(content.replace("\n", " ").split())
        words = base.split(" ")
        title = " ".join(words[:8])
        if len(words) > 8:
            title += "…"
        return title[:60]
    return "New chat"


def generate_coach_conversation_title(
    db: Client,
    athlete_id: str,
    conversation_id: str,
    model_name: str | None = None,
) -> str:
    """
    Builds a short sidebar title from recent coach/athlete messages (sync; call via asyncio.to_thread from async routes).
    """
    rows = _load_conversation_history(db, athlete_id, conversation_id, limit=24)
    transcript = _format_transcript_for_title(rows)
    if not transcript.strip():
        return "New chat"

    effective_model = model_name or settings.GEMINI_MODEL
    prompt = f"{_TITLE_SYSTEM}\n\n---\n{transcript}\n---\nTitle:"
    try:
        # Best-effort background work competing with the chat model's own
        # RPM budget right after a reply — a short wait here means a busy
        # budget just falls back to the heuristic title below instead of
        # eating into the budget the actual chat reply needs.
        gemini_quota.wait_for_slot(effective_model, max_wait_sec=5.0)
        response = _client.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=48, temperature=0.25),
        )
        text = (getattr(response, "text", None) or "").strip()
        title = _sanitize_generated_title(text)
        if len(title) < 4:
            return _fallback_title_from_history(rows)
        return title
    except Exception:
        return _fallback_title_from_history(rows)