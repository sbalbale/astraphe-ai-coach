import pytest

from app.services.ai_coach import load_coach_instructions


def test_markdown_prompt_loading():
    # Ensure the coach behavior file is successfully read
    instructions = load_coach_instructions()
    assert "ASTRAPE" in instructions
    assert "Tool Use Discipline" in instructions or "simulate_training_impact" in instructions


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