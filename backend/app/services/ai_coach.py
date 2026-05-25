from google import genai
from google.genai import types
from app.config import settings
from app.services import coach_tools
from app.services.algorithms import compute_z_score
from app.services.memory import retrieve_relevant_memories
import asyncio
import json
import re
import time
from datetime import date
from typing import Any

import numpy as np
from supabase import Client
from datetime import timedelta


_client = genai.Client(api_key=settings.GEMINI_API_KEY)

def load_coach_instructions() -> str:
    prompt_file = settings.PROMPTS_DIR / settings.COACH_PROMPT_FILE
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are ASTRAPE, an elite, data-driven performance coach."

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
            .select("display_name,gender,timezone_offset_min,resting_hr,hrv_baseline,rhr_baseline,max_hr,threshold_hr,threshold_pace,measurement_units")
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
            "threshold_pace": row.get("threshold_pace"),
        },
    }

def _load_conversation_history(db: Client, athlete_id: str, conversation_id: str, limit: int = 24) -> list[dict]:
    """
    Loads a small, ordered slice of messages for prompt context.
    """
    try:
        res = (
            db.table("coach_messages")
            .select("role,content,image_urls,created_at")
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
                content = _strip_internal_reasoning(content)
            out.append({
                "role": role,
                "content": content,
                "image_urls": r.get("image_urls") or [],
                "created_at": r.get("created_at"),
            })
        return out
    except Exception as e:
        return [{"role": "system", "content": f"history_load_failed: {str(e)}", "image_urls": []}]

# Per-athlete context cache — avoids 3 repeated DB queries across chat messages.
# Keys: athlete_id → (bio, profile, tss_base_dict, expires_at)
_context_parts_cache: dict[str, tuple[dict, dict, dict, float]] = {}
_CONTEXT_CACHE_TTL = 300.0  # 5 minutes


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


def _build_system_context(
    db: Client,
    athlete_id: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
    memories: list[dict] | None = None,
) -> str:
    today = date.today().isoformat()
    bio, profile, tss_base = _get_context_parts_cached(db, athlete_id)
    # Patch current workout TSS (varies per message) into the cached training load dict.
    training_load = {**tss_base, "most_recent_workout_tss": _safe_float(current_tss) or 0.0}
    ctx: dict = {
        "date": today,
        "athlete_id": athlete_id,
        "training_load": training_load,
        "biometrics": bio,
        "athlete_profile": profile,
    }
    if memories:
        ctx["memories"] = [
            {"content": m.get("content"), "created_at": m.get("created_at")}
            for m in memories
        ]
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": _load_conversation_history(db, athlete_id, conversation_id, limit=24),
        }
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(ctx, ensure_ascii=False) + "\n[END CONTEXT]"


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
) -> tuple[str, bool]:
    """
    Proactive first message when chat mounts, or a standard greeting.
    Returns (message_text, is_proactive).
    """
    anomalies = detect_anomalies(db, athlete_id)
    instructions = load_coach_instructions()
    context_block = _build_system_context(db, athlete_id, current_tss=0.0, conversation_id=None)
    effective_model = model_name or settings.GEMINI_MODEL

    if anomalies:
        directive = (
            "[PROACTIVE CHECK]\nThe following severe anomalies were detected (JSON):\n"
            + json.dumps(anomalies, ensure_ascii=False)
            + "\n\nWrite exactly 2–3 sentences. Name the triggering metric(s). Recommend a decisive action. "
            "ASTRAPE voice: conversational and supportive. You may use a relevant emoji. Wrap your final message in <response> ... </response> tags."
        )
    else:
        directive = (
            "[INITIAL GREETING]\nNo severe anomaly triggers fired. "
            "Write at most 2 sentences, context-aware, and cite TSB or HRV from the context. "
            "ASTRAPE voice: conversational and supportive. You may use a relevant emoji. Wrap your final message in <response> ... </response> tags."
        )

    prompt = f"{instructions}\n\n{context_block}\n\n{directive}"
    try:
        response = _client.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=256,
                temperature=0.35,
            ),
        )
        text = _extract_athlete_message_from_model_output(response)
    except Exception as e:
        text = f"Initialization failed: {e}"
    return text, bool(anomalies)


def _history_to_gemini_contents(history: list[dict]) -> list[types.Content]:
    """Map coach_messages rows to Gemini Content (user / model)."""
    out: list[types.Content] = []
    for r in history:
        raw_role = (r.get("role") or "").strip()
        content = (r.get("content") or "").strip()
        if not content:
            continue
        if raw_role not in ("user", "ai"):
            continue
        if raw_role == "ai":
            content = _strip_internal_reasoning(content).strip()
            if not content:
                continue
        grole = "user" if raw_role == "user" else "model"
        out.append(types.Content(role=grole, parts=[types.Part.from_text(text=content)]))
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


def _extract_athlete_message_from_model_output(response: Any) -> str:
    """Extracts text from Gemini response and passes it to the XML parser."""
    raw_text = (getattr(response, "text", None) or "").strip()
    return _extract_athlete_message_from_text(raw_text)


_SCRATCHPAD_RE = re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL | re.IGNORECASE)
_READY_MARKER_RE = re.compile(r"\*Ready\.\*", re.IGNORECASE)
_COACH_REPLY_START_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"Because (?:the |your |with |how )|"
    r"Given how (?:much |your )|"
    r"Hey \w|"
    r"Here is how (?:I )?recommend|"
    r"Here are|"
    r"That \d|"
    r"That (?:is|was|sounds|looks|effort)|"
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
    Cleaner extraction: strips any lingering XML scratchpad tags but otherwise 
    treats the terminal output as the athlete message.
    """
    raw = (raw_text or "").strip()
    if not raw:
        return ""

    # Strip legacy or hallucinated scratchpad tags
    raw = _SCRATCHPAD_RE.sub("", raw).strip()

    # Legacy XML response support (backwards compatibility)
    match = re.search(r"<response>(.*?)</response>", raw, re.DOTALL | re.IGNORECASE)
    if match:
        cleaned = _strip_internal_reasoning(match.group(1))
        return cleaned or "I encountered an error processing your request."

    # In the new Agentic Scratchpad pattern, the raw text IS the response
    cleaned = _strip_internal_reasoning(raw)
    return cleaned or "I encountered an error processing your request."


def _strip_internal_reasoning(text: str) -> str:
    """
    Backstop sanitizer: if the model emits chain-of-thought style scaffolding, drop it.
    """
    t = _SCRATCHPAD_RE.sub("", (text or "")).strip()
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
        if any(k in low for k in ("ctl", "atl", "tsb", "hrv", "rmssd", "sleep score")) and (("." in s) or (":" in s)):
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
        if low.startswith(("wait", "actually", "final", "draft")) or (
            low.startswith("the user") and "asking" in low
        ):
            i += 1
            continue
        break

    out = "\n".join(ln for ln in lines[i:] if ln.strip()).strip()
    if out:
        return out

    return t


def get_coach_response_agentic(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    max_tool_hops: int = 15,
) -> tuple[str, list[dict[str, str]]]:
    """
    Non-streaming coach reply with manual Gemini function calling (tool loop).
    Returns (athlete-facing message, web search citation sources when present).
    """
    system_instruction = load_coach_instructions()
    memories = retrieve_relevant_memories(athlete_id, message, db, top_k=5) if db else []
    context_block = (
        _build_system_context(db, athlete_id, current_tss=current_tss, conversation_id=conversation_id, memories=memories)
        if db
        else f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
    )
    system_with_ctx = f"{system_instruction}\n\n{context_block}"

    if not db:
        final_prompt = f"{system_with_ctx}\n\nAthlete Message: {message}"
        effective_model = model_name or settings.GEMINI_MODEL
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
    contents = _history_to_gemini_contents(history)
    # Always append the current user message (history alone is not sufficient).
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
    # If there was no history, `contents` is now a 1-item list with the current message.

    # Deterministic backstop: if the user requests clearing a plan, do it even if the model doesn't call tools.
    msg_l = (message or "").lower()
    wants_clear = any(k in msg_l for k in ("delete", "remove", "clear")) and ("plan" in msg_l or "calendar" in msg_l)
    if wants_clear:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        if "next week" in msg_l:
            start = monday + timedelta(days=7)
            end = monday + timedelta(days=13)
        elif "this week" in msg_l:
            start = monday
            end = monday + timedelta(days=6)
        else:
            start = None
            end = None

        if start and end:
            res = coach_tools.handle_clear_training_plans(
                {"start_date": start.isoformat(), "end_date": end.isoformat()},
                athlete_id=athlete_id,
                db=db,
            )
            # Feed tool output into the conversation so the model can acknowledge it.
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name="clear_training_plans",
                            response=res,
                        )
                    ],
                )
            )

    effective_model = model_name or settings.GEMINI_MODEL
    # Only use ThinkingConfig for models that specifically support it
    is_thinking_model = "thinking" in effective_model.lower()
    
    config = types.GenerateContentConfig(
        system_instruction=system_with_ctx,
        tools=coach_tools.TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            include_server_side_tool_invocations=True
        ),
        temperature=0.4,
    )
    if is_thinking_model:
        config.thinking_config = types.ThinkingConfig(include_thoughts=False)

    last_response = None
    # Reduced max hops to prevent long hangs on heavy models or tool-call oscillations
    for _hop in range(8):
        _hop_error: Exception | None = None
        for _attempt in range(3):  # 3 attempts for larger models
            try:
                last_response = _client.models.generate_content(
                    model=effective_model,
                    contents=contents,
                    config=config,
                )
                _hop_error = None
                break
            except Exception as e:
                _hop_error = e
                err_str = str(e)
                # Catch broad transient errors and connection-level failures
                is_transient = any(
                    k in err_str 
                    for k in ("500", "503", "INTERNAL", "overloaded", "Server disconnected", "RemoteProtocolError", "EOF")
                )
                if _attempt < 2 and is_transient:
                    wait = 1.5 * (_attempt + 1)
                    print(f"[coach] Gemini transient error (hop {_hop}, attempt {_attempt + 1}): {e}. Retrying in {wait}s…")
                    time.sleep(wait)
                    continue
                break

        if _hop_error is not None:
            print(f"CRITICAL: generate_content failed after retry (hop {_hop}): {_hop_error}")
            tail = contents[-1] if contents else None
            parts_iter = getattr(tail, "parts", None)
            parts_list = list(parts_iter) if parts_iter else []
            if parts_list and any(
                getattr(p, "function_response", None) for p in parts_list
            ):
                return (
                    "I have successfully processed your data and updated your status. Please let me know if you need anything else!",
                    [],
                )
            raise _hop_error

        if not last_response.candidates:
            break
        cand = last_response.candidates[0]
        if not cand.content or not cand.content.parts:
            break

        parts = list(cand.content.parts)
        fcs = [p.function_call for p in parts if p.function_call]
        texts = [p.text for p in parts if p.text]

        if fcs:
            fc_parts: list[types.Part] = []
            for fc in fcs:
                if fc is None:
                    continue
                fc_parts.append(types.Part(function_call=fc))
            if not fc_parts:
                break
            contents.append(types.Content(role="model", parts=fc_parts))

            fr_parts: list[types.Part] = []
            for fc in fcs:
                if fc is None or not fc.name:
                    continue
                name = fc.name
                args = coach_tools.parse_function_args(fc)
                handler = coach_tools.TOOL_HANDLERS.get(name)
                try:
                    result: dict[str, Any] = (
                        handler(args, athlete_id, db) if handler else {"error": f"unknown_tool:{name}"}
                    )
                except Exception as e:
                    result = {"error": str(e)}
                print(f"\n--- [TOOL EXECUTED: {name}] ---")
                print(f"Args: {args}")
                print(f"Result: {result}\n")
                fr_parts.append(types.Part.from_function_response(name=name, response=result))
            if fr_parts:
                contents.append(types.Content(role="user", parts=fr_parts))
            continue

        joined = "".join(t for t in texts if t)
        if joined.strip():
            return (
                _extract_athlete_message_from_text(joined),
                _extract_grounding_sources(last_response),
            )
        fallback = getattr(last_response, "text", None) or ""
        if fallback.strip():
            return (
                _extract_athlete_message_from_text(fallback),
                _extract_grounding_sources(last_response),
            )
        break

    fallback = getattr(last_response, "text", None) or "" if last_response else ""
    final = _extract_athlete_message_from_text(fallback)
    grounding = _extract_grounding_sources(last_response) if last_response else []
    return (final or "Unable to complete coach response.", grounding)


async def _build_system_context_string_async(
    db: Client,
    athlete_id: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
    query: str | None = None,
) -> str:
    """
    Same payload as _build_system_context, but DB reads run in parallel to cut
    time-to-first-token on /v1/coach/stream (four sequential round-trips → one wait).
    """
    today = date.today().isoformat()

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

    training, bio, profile, hist_rows, memories = await asyncio.gather(
        asyncio.to_thread(_summarize_training_load, db, athlete_id, current_tss),
        asyncio.to_thread(_summarize_biometrics, db, athlete_id),
        asyncio.to_thread(_summarize_athlete_profile, db, athlete_id),
        load_hist(),
        load_memories(),
    )
    ctx: dict = {
        "date": today,
        "athlete_id": athlete_id,
        "training_load": training,
        "biometrics": bio,
        "athlete_profile": profile,
    }
    if memories:
        ctx["memories"] = [
            {"content": m.get("content"), "created_at": m.get("created_at")}
            for m in memories
        ]
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": hist_rows,
        }
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(ctx, ensure_ascii=False) + "\n[END CONTEXT]"


def get_coach_response(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    return get_coach_response_agentic(
        athlete_id=athlete_id,
        message=message,
        current_tss=current_tss,
        db=db,
        conversation_id=conversation_id,
        model_name=model_name,
    )

async def get_coach_response_stream(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
):
    system_instruction = load_coach_instructions()
    if db:
        context_block = await _build_system_context_string_async(
            db, athlete_id, current_tss=current_tss, conversation_id=conversation_id
        )
    else:
        context_block = (
            f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
        )
    final_prompt = f"{system_instruction}\n\n{context_block}\n\nAthlete Message: {message}"
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
        t = getattr(chunk, "text", None)
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