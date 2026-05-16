from __future__ import annotations

from app.config import settings


def resolve_default_gemini_model() -> str:
    """
    Backend fallback Gemini model name (from .env / settings).
    """
    return (settings.GEMINI_MODEL or "").strip() or "gemma-4-31b-it"

