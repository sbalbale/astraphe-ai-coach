from google import genai
from google.genai import types
from app.config import settings
from app.services import coach_tools
from app.services.algorithms import compute_z_score
import asyncio
import json
import re
from datetime import date
from typing import Any

import numpy as np
from supabase import Client

_client = genai.Client(api_key=settings.GEMINI_API_KEY)

def get_embedding_model_name() -> str:
    embedding_model = settings.GEMINI_EMBEDDING_MODEL
    return embedding_model if embedding_model.startswith("models/") else f"models/{embedding_model}"

def load_coach_instructions() -> str:
    prompt_file = settings.PROMPTS_DIR / settings.COACH_PROMPT_FILE
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are ASTRAPE, an elite, data-driven performance coach."

async def retrieve_relevant_memories(athlete_id: str, query: str, db: Client, top_k: int = 5) -> list[dict]:
    resp = _client.models.embed_content(
        model=get_embedding_model_name(),
        contents=query,
    )
    # Best-effort extraction across SDK versions.
    query_embedding = None
    emb = getattr(resp, "embedding", None)
    if emb is None:
        emb = getattr(resp, "embeddings", None)
    if emb is not None:
        if isinstance(emb, dict):
            query_embedding = emb.get("values") or emb.get("embedding") or emb.get("vector")
        elif isinstance(emb, (list, tuple)) and emb:
            first = emb[0]
            query_embedding = getattr(first, "values", None) or getattr(first, "embedding", None)
        else:
            query_embedding = getattr(emb, "values", None)
    if query_embedding is None:
        # Fall back to dict-like behavior if the response supports it.
        try:
            query_embedding = resp["embedding"]  # type: ignore[index]
        except Exception:
            query_embedding = []
    result = db.rpc("match_coach_memories", {
        "athlete_id": athlete_id, "query_embedding": query_embedding, "match_threshold": 0.75, "match_count": top_k
    }).execute()
    return result.data

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

def _summarize_biometrics(db: Client, athlete_id: str) -> dict:
    """
    Pull a compact biometrics summary for LLM context.
    Keeps payload small: latest day + 7-day averages where possible.
    """
    try:
        bio_res = (
            db.table("biometrics")
            .select(
                "date,hrv_rmssd,resting_hr,sleep_duration_min,sleep_score,recovery_score,readiness_score,"
                "strain_score,spo2_pct,skin_temp_deviation"
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
            "skin_temp_deviation": _safe_float(latest.get("skin_temp_deviation")),
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
            "skin_temp_deviation": avg("skin_temp_deviation"),
        },
    }

    # Add simple deltas vs 7d avg for the most important signals
    for k in ("hrv_rmssd", "resting_hr", "sleep_duration_min", "sleep_score", "recovery_score", "spo2_pct", "skin_temp_deviation"):
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
            .select("display_name,gender,timezone_offset_min,resting_hr,hrv_baseline,rhr_baseline,max_hr,threshold_hr,threshold_pace")
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
            out.append({
                "role": r.get("role"),
                "content": r.get("content"),
                "image_urls": r.get("image_urls") or [],
                "created_at": r.get("created_at"),
            })
        return out
    except Exception as e:
        return [{"role": "system", "content": f"history_load_failed: {str(e)}", "image_urls": []}]

def _build_system_context(db: Client, athlete_id: str, current_tss: float = 0.0, conversation_id: str | None = None) -> str:
    today = date.today().isoformat()
    ctx = {
        "date": today,
        "athlete_id": athlete_id,
        "training_load": _summarize_training_load(db, athlete_id, current_tss=current_tss),
        "biometrics": _summarize_biometrics(db, athlete_id),
        "athlete_profile": _summarize_athlete_profile(db, athlete_id),
    }
    if conversation_id:
        ctx["conversation"] = {
            "id": conversation_id,
            "recent_messages": _load_conversation_history(db, athlete_id, conversation_id, limit=24),
        }
    # Keep prompt reasonably compact; JSON is easiest for LLM to parse reliably.
    return "[SYSTEM CONTEXT - DO NOT SHOW TO USER]\n" + json.dumps(ctx, ensure_ascii=False) + "\n[END CONTEXT]"


def detect_anomalies(db: Client, athlete_id: str) -> dict[str, Any] | None:
    """
    Returns a dict with triggered signals if any severe rule fires; otherwise None.
    Thresholds: HRV z < -1.5, sleep_debt > 90 min, RHR > 7d avg + 5, TSB < -30, skin_temp > 0.6°C.
    """
    signals: list[dict[str, Any]] = []

    # --- HRV z (30-row window, 7d EWMA baseline on prior readings; match /v1/athlete/state) ---
    try:
        bio_window_res = (
            db.table("biometrics")
            .select("date,hrv_rmssd,resting_hr,sleep_duration_min,sleep_debt_min,skin_temp_deviation")
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

    # --- RHR vs 7d average ---
    bio_summary = _summarize_biometrics(db, athlete_id)
    if bio_summary.get("available"):
        lr = _safe_int(bio_summary["latest"].get("resting_hr"))
        av = _safe_float(bio_summary["avg_7d"].get("resting_hr"))
        if lr is not None and av is not None and lr > av + 5:
            signals.append({
                "metric": "resting_hr_delta",
                "resting_hr": lr,
                "avg_7d_rhr": round(av, 1),
                "threshold_bpm_above_avg": 5,
            })
        st = _safe_float(bio_summary["latest"].get("skin_temp_deviation"))
        if st is not None and st > 0.6:
            signals.append({
                "metric": "skin_temp_deviation_c",
                "value": round(st, 3),
                "threshold": 0.6,
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
            + "\n\nWrite exactly 2–3 sentences. Name the triggering metric(s) with concrete values. "
            "Recommend a decisive action (e.g. cancel threshold work, swap for recovery). "
            "ASTRAPE voice: clinical, no emojis."
        )
    else:
        directive = (
            "[INITIAL GREETING]\nNo severe anomaly triggers fired. "
            "Write at most 2 sentences, context-aware, and cite TSB or HRV from the context. "
            "ASTRAPE voice: clinical, no emojis."
        )

    prompt = f"{instructions}\n\n{context_block}\n\n{directive}"
    try:
        response = _client.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=256, temperature=0.35),
        )
        text = (getattr(response, "text", None) or "").strip()
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
        grole = "user" if raw_role == "user" else "model"
        out.append(types.Content(role=grole, parts=[types.Part.from_text(text=content)]))
    return out


def get_coach_response_agentic(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
    max_tool_hops: int = 4,
) -> str:
    """
    Non-streaming coach reply with manual Gemini function calling (tool loop).
    """
    system_instruction = load_coach_instructions()
    context_block = (
        _build_system_context(db, athlete_id, current_tss=current_tss, conversation_id=conversation_id)
        if db
        else f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
    )
    system_with_ctx = f"{system_instruction}\n\n{context_block}"

    if not db:
        final_prompt = f"{system_with_ctx}\n\nAthlete Message: {message}"
        effective_model = model_name or settings.GEMINI_MODEL
        response = _client.models.generate_content(model=effective_model, contents=final_prompt)
        return getattr(response, "text", "") or ""

    history = (
        _load_conversation_history(db, athlete_id, conversation_id, limit=24)
        if conversation_id
        else []
    )
    contents = _history_to_gemini_contents(history)
    if not contents:
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=message)])]

    effective_model = model_name or settings.GEMINI_MODEL
    config = types.GenerateContentConfig(
        system_instruction=system_with_ctx,
        tools=coach_tools.TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.35,
    )

    last_response = None
    for _hop in range(max_tool_hops + 1):
        last_response = _client.models.generate_content(
            model=effective_model,
            contents=contents,
            config=config,
        )
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
                fr_parts.append(types.Part.from_function_response(name=name, response=result))
            if fr_parts:
                contents.append(types.Content(role="user", parts=fr_parts))
            continue

        joined = "".join(t for t in texts if t)
        if joined.strip():
            return joined.strip()
        fallback = getattr(last_response, "text", None) or ""
        if fallback.strip():
            return fallback.strip()
        break

    fallback = getattr(last_response, "text", None) or "" if last_response else ""
    return fallback.strip() or "Unable to complete coach response."


async def _build_system_context_string_async(
    db: Client,
    athlete_id: str,
    current_tss: float = 0.0,
    conversation_id: str | None = None,
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

    training, bio, profile, hist_rows = await asyncio.gather(
        asyncio.to_thread(_summarize_training_load, db, athlete_id, current_tss),
        asyncio.to_thread(_summarize_biometrics, db, athlete_id),
        asyncio.to_thread(_summarize_athlete_profile, db, athlete_id),
        load_hist(),
    )
    ctx: dict = {
        "date": today,
        "athlete_id": athlete_id,
        "training_load": training,
        "biometrics": bio,
        "athlete_profile": profile,
    }
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
) -> str:
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
    for chunk in _client.models.generate_content_stream(model=effective_model, contents=final_prompt):
        t = getattr(chunk, "text", None)
        if t:
            yield t


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