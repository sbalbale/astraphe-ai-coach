from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from app.config import settings


def _normalize_model_name(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return None


def resolve_gemini_model_for_athlete(db: Client, athlete_id: str) -> str:
    """
    Returns the preferred Gemini model for this athlete, falling back to env default.
    Storage location: public.athletes.ai_settings->>'gemini_model'
    """
    fallback = (settings.GEMINI_MODEL or "").strip() or "gemini-flash-lite-latest"
    try:
        res = (
            db.table("athletes")
            .select("ai_settings")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = res.data if res else None
        ai_settings = (row or {}).get("ai_settings") if isinstance(row, dict) else None
        if isinstance(ai_settings, dict):
            m = _normalize_model_name(ai_settings.get("gemini_model"))
            if m:
                return m
        return fallback
    except Exception:
        return fallback

