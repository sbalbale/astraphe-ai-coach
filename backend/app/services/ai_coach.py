from google import genai
from google.genai import types
from app.config import settings
import json
from datetime import date
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

def get_coach_response(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
) -> str:
    system_instruction = load_coach_instructions()
    context_block = _build_system_context(db, athlete_id, current_tss=current_tss, conversation_id=conversation_id) if db else (
        f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
    )
    final_prompt = f"{system_instruction}\n\n{context_block}\n\nAthlete Message: {message}"
    effective_model = (model_name or settings.GEMINI_MODEL)
    response = _client.models.generate_content(model=effective_model, contents=final_prompt)
    return getattr(response, "text", "") or ""

async def get_coach_response_stream(
    athlete_id: str,
    message: str,
    current_tss: float = 0.0,
    db: Client | None = None,
    conversation_id: str | None = None,
    model_name: str | None = None,
):
    system_instruction = load_coach_instructions()
    context_block = _build_system_context(db, athlete_id, current_tss=current_tss, conversation_id=conversation_id) if db else (
        f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
    )
    final_prompt = f"{system_instruction}\n\n{context_block}\n\nAthlete Message: {message}"
    effective_model = (model_name or settings.GEMINI_MODEL)
    for chunk in _client.models.generate_content_stream(model=effective_model, contents=final_prompt):
        t = getattr(chunk, "text", None)
        if t:
            yield t