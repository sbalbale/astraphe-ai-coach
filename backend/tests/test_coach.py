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


@pytest.mark.skip(reason="Requires live Supabase + Gemini; use E2E or mock get_user_db.")
def test_coach_api_response(client, test_athlete_id):
    payload = {
        "athlete_id": test_athlete_id,
        "message": "I have an exam today, how should I train?",
        "recent_tss": 50.0,
    }
    response = client.post("/v1/coach/message", json=payload)
    assert response.status_code == 200
    assert "reply" in response.json()