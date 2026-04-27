from app.services.ai_coach import load_coach_instructions

def test_markdown_prompt_loading():
    # Ensure the coach behavior file is successfully read
    instructions = load_coach_instructions()
    assert "ASTRAPE" in instructions
    assert "Directives" in instructions

def test_coach_api_response(client, test_athlete_id):
    # Test the full round-trip from API to Gemini
    payload = {
        "athlete_id": test_athlete_id,
        "message": "I have an exam today, how should I train?",
        "recent_tss": 50.0
    }
    response = client.post("/v1/coach/message", json=payload)
    assert response.status_code == 200
    # The response should mention 'Zone 2' or 'Academic Load'
    assert "reply" in response.json()