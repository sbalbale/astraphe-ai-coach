import pytest
from types import SimpleNamespace

from app.services.ai_coach import (
    _extract_athlete_message_from_text,
    _load_conversation_history,
    load_coach_instructions,
    _extract_grounding_sources,
)


def test_markdown_prompt_loading():
    # Ensure the coach behavior file is successfully read
    instructions = load_coach_instructions()
    assert "ASTRAPE" in instructions
    assert "Tool Use Discipline" in instructions or "simulate_training_impact" in instructions
    assert "Live Web Search" in instructions


def test_extract_athlete_message_strips_scratchpad_tags():
    raw = (
        "<scratchpad>Internal planning only.</scratchpad>"
        "<response>Because your HRV dipped, rest today.</response>"
    )
    assert _extract_athlete_message_from_text(raw) == "Because your HRV dipped, rest today."


def test_extract_athlete_message_strips_thinking_dump_before_ready_marker():
    raw = (
        "The user is asking for advice on training intensity next week.\n"
        "* Current Date: 2026-05-22 (Friday).\n"
        "* Current TSB (Form): -13.86.\n"
        "* Step 1: Simulate the impact of the Pemi Loop.\n"
        "* Wait, I should check if I can use simulate_training_impact.\n"
        "*Ready.*Because the Pemi Loop is going to be such a massive physiological tax, "
        "next week needs to be a dedicated Recovery week.\n"
        "| Day | Discipline | Duration | Intensity/Zone |\n"
        "| Mon | Rest | - | Complete Rest |"
    )
    out = _extract_athlete_message_from_text(raw)
    assert "The user is asking" not in out
    assert "Step 1:" not in out
    assert "Wait, I should" not in out
    assert out.startswith("Because the Pemi Loop")
    assert "Recovery week" in out
    assert "Day | Discipline" in out or "Mon | Rest" in out


def test_extract_athlete_message_strips_scratchpad_without_response_tags():
    raw = (
        "<scratchpad>\n"
        "Plan the deload week.\n"
        "* Constraint Check: cite a metric.\n"
        "</scratchpad>\n"
        "Given how much your HRV has dipped, I would recommend complete rest."
    )
    out = _extract_athlete_message_from_text(raw)
    assert "Constraint Check" not in out
    assert "Plan the deload" not in out
    assert out.startswith("Given how much your HRV")


def test_extract_athlete_message_strips_triathlon_planning_dump():
    raw = (
        "The user is asking about their swimming performance and how to improve front crawl.\n"
        "750m breaststroke at 2:15/100m.\n"
        "* Is this good? For a beginner triathlete, it is a solid baseline.\n"
        "* The search results say the Cohasset swim is a 0.25-mile ocean swim.\n"
        "Plan:\n"
        "Acknowledge the race and the swim effort.\n"
        "Constraint Check:\n"
        "No quotation marks for emphasis.\n"
        "Let's refine the Is it good part.\n"
        "Final response structure:\n"
        "That 750m effort is a fantastic baseline, Sean! To answer your question: "
        "an average of 2:15 per 100m for breaststroke is a very solid starting point.\n"
        "How to Improve Your Front Crawl\n"
        "Start with catch-up drill and fingertip drag drill."
    )
    out = _extract_athlete_message_from_text(raw)
    assert out.startswith("That 750m effort")
    assert "The user is asking" not in out
    assert "Plan:" not in out
    assert "Constraint Check" not in out
    assert "Final response structure" not in out
    assert "Let's refine" not in out
    assert "2:15 per 100m" in out


def test_load_conversation_history_sanitizes_persisted_ai_reasoning(fake_db, test_athlete_id):
    fake_db._table_seeds["coach_messages"] = [
        {
            "role": "ai",
            "content": (
                "The user is asking about their swimming performance.\n"
                "Plan:\n"
                "Answer directly.\n"
                "That 750m effort is a fantastic baseline, Sean!"
            ),
            "image_urls": [],
            "created_at": "2026-05-25T19:00:00Z",
        }
    ]

    rows = _load_conversation_history(fake_db, test_athlete_id, "fake-conversation-id")

    assert rows[0]["content"] == "That 750m effort is a fantastic baseline, Sean!"


def test_get_conversation_messages_sanitizes_persisted_ai_reasoning(coach_client, fake_db):
    fake_db._table_seeds["coach_messages"] = [
        {
            "id": "leaky-message",
            "role": "ai",
            "content": (
                "The user is asking about front crawl.\n"
                "Constraint Check:\n"
                "Cite a metric.\n"
                "That 750m effort is a fantastic baseline, Sean!"
            ),
            "image_urls": [],
            "created_at": "2026-05-25T19:00:00Z",
        }
    ]

    response = coach_client.get("/v1/coach/conversations/fake-conversation-id/messages")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["messages"][0]["content"] == "That 750m effort is a fantastic baseline, Sean!"


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