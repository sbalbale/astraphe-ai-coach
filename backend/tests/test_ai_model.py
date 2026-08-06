from app.config import settings
from app.services.ai_model import resolve_default_gemini_model


def test_resolve_default_gemini_model_returns_configured_value(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-flash-lite-test")

    assert resolve_default_gemini_model() == "gemini-flash-lite-test"


def test_resolve_default_gemini_model_strips_whitespace(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "  gemini-pro  ")

    assert resolve_default_gemini_model() == "gemini-pro"


def test_resolve_default_gemini_model_falls_back_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "")

    assert resolve_default_gemini_model() == "gemma-4-31b-it"


def test_resolve_default_gemini_model_falls_back_when_only_whitespace(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "   ")

    assert resolve_default_gemini_model() == "gemma-4-31b-it"
