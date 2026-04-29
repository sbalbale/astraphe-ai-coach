from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import google.generativeai as genai
from supabase import Client

from app.config import settings


genai.configure(api_key=settings.GEMINI_API_KEY)


AnalysisRow = Dict[str, Any]


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def canonical_json(obj: Any) -> str:
    # Stable serialization for hashing.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint_context(context: Any) -> str:
    s = canonical_json(context)
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


def generate_gemini_analysis(prompt: str) -> Tuple[str, str]:
    model_name = settings.GEMINI_MODEL
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(prompt)
    text = getattr(resp, "text", "") or ""
    return clamp_to_two_sentences(text), model_name

