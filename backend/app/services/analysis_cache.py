from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from google import genai
from supabase import Client

from app.config import settings


_client = genai.Client(api_key=settings.GEMINI_API_KEY)


AnalysisRow = Dict[str, Any]

_MAX_MODEL_ERROR_LEN = 400


def sanitize_error_for_model(err: Exception | str | None) -> str:
    if err is None:
        return "unknown"
    s = str(err).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > _MAX_MODEL_ERROR_LEN:
        return s[:_MAX_MODEL_ERROR_LEN] + "…"
    return s or "unknown"


def format_analysis_failure_model(
    requested_model: str,
    failure: str,
    error: Exception | str | None = None,
) -> str:
    """
    Persist failure kind + error text in the `model` column, e.g.
    gemini-flash-lite-latest:error_fallback:429 Resource exhausted
    """
    base = (requested_model or settings.GEMINI_ANALYSIS_MODEL or "gemini").strip()
    if error is not None:
        return f"{base}:{failure}:{sanitize_error_for_model(error)}"
    return f"{base}:{failure}"


def is_retryable_failed_analysis(model: Optional[str]) -> bool:
    """True when cache holds fallback text from a failed Gemini call (should retry)."""
    if not model or model == "fallback":
        return False
    return ":error_fallback" in model or ":empty_fallback" in model


def analysis_cache_is_valid(cached: Optional[AnalysisRow], fingerprint: str) -> bool:
    if not cached or not cached.get("content"):
        return False
    if cached.get("fingerprint") != fingerprint:
        return False
    if is_retryable_failed_analysis(cached.get("model")):
        return False
    return True


def _now_iso() -> str:
    # Timezone-aware UTC; preserve legacy 'Z' suffix on the wire.
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(obj: Any) -> str:
    # Stable serialization for hashing.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snap_floats_for_fingerprint(obj: Any) -> Any:
    """
    PostgREST / driver float noise (e.g. 12.3000000001 vs 12.3) should not invalidate cache.
    """
    if isinstance(obj, float):
        return round(obj, 4)
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, dict):
        return {k: _snap_floats_for_fingerprint(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_snap_floats_for_fingerprint(v) for v in obj]
    return obj


def fingerprint_context(context: Any) -> str:
    s = canonical_json(_snap_floats_for_fingerprint(context))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


_sentence_split_re = re.compile(r"(?<=[.!?])\s+")


def clamp_to_two_sentences(text: str) -> str:
    """
    Enforces 1–2 sentence output (best-effort).
    Also strips obvious list formatting.
    """
    t = (text or "").strip()
    if not t:
        return ""

    # Remove leading bullets/numbering on each line.
    lines = [re.sub(r"^\s*([-*•]|\d+[\).\]])\s+", "", ln).strip() for ln in t.splitlines()]
    t = " ".join([ln for ln in lines if ln])
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""

    parts = [p.strip() for p in _sentence_split_re.split(t) if p.strip()]
    if len(parts) <= 2:
        return t
    return " ".join(parts[:2]).strip()


def get_cached_analysis(
    db: Client,
    athlete_id: str,
    analysis_type: str,
    scope_key: str,
) -> Optional[AnalysisRow]:
    try:
        res = (
            db.table("athlete_analyses")
            .select("fingerprint,content,model,updated_at")
            .eq("athlete_id", athlete_id)
            .eq("analysis_type", analysis_type)
            .eq("scope_key", scope_key)
            .maybe_single()
            .execute()
        )
        return res.data if res and res.data else None
    except Exception:
        return None


def upsert_analysis(
    db: Client,
    athlete_id: str,
    analysis_type: str,
    scope_key: str,
    fingerprint: str,
    content: str,
    model: str,
) -> None:
    try:
        db.table("athlete_analyses").upsert(
            {
                "athlete_id": athlete_id,
                "analysis_type": analysis_type,
                "scope_key": scope_key,
                "fingerprint": fingerprint,
                "content": content,
                "model": model,
                "updated_at": _now_iso(),
            },
            on_conflict="athlete_id,analysis_type,scope_key",
        ).execute()
    except Exception:
        # Caching failures shouldn't block responses.
        return


def generate_gemini_analysis(prompt: str, model_name: str) -> Tuple[str, str]:
    requested = (model_name or settings.GEMINI_ANALYSIS_MODEL).strip()
    fallback = (settings.GEMINI_ANALYSIS_MODEL or "gemini-flash-lite-latest").strip()
    candidates = [requested]
    if fallback and fallback not in candidates:
        candidates.append(fallback)

    last_err: Exception | None = None
    for effective_model in candidates:
        try:
            resp = _client.models.generate_content(model=effective_model, contents=prompt)
            text = getattr(resp, "text", "") or ""
            return clamp_to_two_sentences(text), effective_model
        except Exception as e:
            last_err = e
            err_text = str(e)
            if "404" in err_text or "NOT_FOUND" in err_text:
                print(f"[analysis] model {effective_model} unavailable, trying fallback")
                continue
            raise

    if last_err is not None:
        raise last_err
    return "", requested

