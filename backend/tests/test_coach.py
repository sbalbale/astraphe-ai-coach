import pytest
from types import SimpleNamespace

from app.services.ai_coach import load_coach_instructions, _extract_grounding_sources


def test_markdown_prompt_loading():
    # Ensure the coach behavior file is successfully read
    instructions = load_coach_instructions()
    assert "ASTRAPE" in instructions
    assert "Tool Use Discipline" in instructions or "simulate_training_impact" in instructions
    assert "Live Web Search" in instructions


def test_extract_grounding_sources_dedupes_and_skips_empty():
    web_a = SimpleNamespace(title="Forecast", uri="https://weather.example/a")
    web_b = SimpleNamespace(title="Race", uri="https://race.example/")
    chunk_a = SimpleNamespace(web=web_a)
    chunk_b = SimpleNamespace(web=web_b)
    chunk_nop = SimpleNamespace(web=None)
    gm = SimpleNamespace(grounding_chunks=[chunk_a, chunk_nop, chunk_a, chunk_b])
    cand = SimpleNamespace(grounding_metadata=gm)
    resp = SimpleNamespace(candidates=[cand])
    out = _extract_grounding_sources(resp)
    assert out == [
        {"title": "Forecast", "url": "https://weather.example/a"},
        {"title": "Race", "url": "https://race.example/"},
    ]


def test_coach_api_response(coach_client, test_athlete_id, monkeypatch):
    """
    End-to-end exercise of POST /v1/coach/message with all external services
    (Supabase + Gemini) replaced by in-process fakes. Validates the response
    contract and the route's orchestration of conversation + message persistence.
    """
    from app.routers import coach as coach_router

    # Stub the two Gemini-touching calls inside the route so the agentic loop
    # and the title generator never reach for the real SDK.
    monkeypatch.setattr(
        coach_router,
        "get_coach_response",
        lambda *args, **kwargs: (
            "Light spin only — protect glycogen and CNS for the exam.",
            [{"title": "Pre-exam fueling", "url": "https://example.com/fuel"}],
        ),
    )
    monkeypatch.setattr(
        coach_router,
        "generate_coach_conversation_title",
        lambda *args, **kwargs: "Exam Day Training",
    )

    payload = {
        "message": "I have an exam today, how should I train?",
        "recent_tss": 50.0,
    }
    response = coach_client.post("/v1/coach/message", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["conversation_id"] == "fake-conversation-id"
    assert "reply" in body
    assert body["reply"].startswith("Light spin")
    assert body["sources"] == [
        {"title": "Pre-exam fueling", "url": "https://example.com/fuel"}
    ]