import pytest
from types import SimpleNamespace

from app.services.ai_coach import (
    _calendar_preface,
    _extract_athlete_message_from_text,
    _extract_athlete_message_from_model_output,
    _extract_non_thought_text_from_response,
    _load_conversation_history,
    load_coach_instructions,
    _extract_grounding_sources,
    _normalize_relative_tool_dates,
)


def test_markdown_prompt_loading():
    # Ensure the coach behavior file is successfully read
    instructions = load_coach_instructions()
    assert "ASTRAPE" in instructions
    assert "Tool Use Discipline" in instructions or "simulate_training_impact" in instructions
    assert "Live Web Search" in instructions
    assert "<response>" in instructions


def test_extract_athlete_message_strips_scratchpad_tags():
    raw = (
        "<scratchpad>Internal planning only.</scratchpad>"
        "<response>Because your HRV dipped, rest today.</response>"
    )
    assert _extract_athlete_message_from_text(raw) == "Because your HRV dipped, rest today."


def test_extract_athlete_message_prefers_final_response_xml():
    raw = (
        "<scratchpad>Internal planning only. <response>Wrong draft.</response></scratchpad>\n"
        "<response>Because your HRV dipped, rest today.</response>"
    )
    assert _extract_athlete_message_from_text(raw) == "Because your HRV dipped, rest today."


def test_extract_model_output_filters_thought_parts():
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="THOUGHT: Hidden reasoning.\n\n", thought=True),
                        SimpleNamespace(text="<response>Keep the swim easy today.</response>", thought=False),
                    ]
                )
            )
        ],
        text="THOUGHT: Hidden reasoning.\n\n<response>Fallback should not be needed.</response>",
    )

    assert _extract_non_thought_text_from_response(response) == "<response>Keep the swim easy today.</response>"
    assert _extract_athlete_message_from_model_output(response) == "Keep the swim easy today."


def test_extract_model_output_does_not_fallback_when_only_thought_parts():
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="THOUGHT: Hidden reasoning.", thought=True),
                    ]
                )
            )
        ],
        text="THOUGHT: Hidden reasoning.",
    )

    assert _extract_non_thought_text_from_response(response) == ""


def test_extract_athlete_message_strips_thought_prefix_fallback():
    raw = (
        "THOUGHT: Check TSB, HRV, and recovery before answering.\n\n"
        "That changes things significantly! Keep the ball-machine tennis controlled."
    )
    out = _extract_athlete_message_from_text(raw)
    assert out.startswith("That changes things significantly!")
    assert "THOUGHT:" not in out


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


def test_extract_athlete_message_strips_followup_planning_dump_with_metrics():
    raw = (
        "Remind them of the metrics: Their recovery score (79) and TSB (-5.92) still support this.\n"
        "Ask if they want me to schedule the Threshold Run for Wednesday or if they want to pivot the whole day's plan.\n"
        "Wait, the user's message means this sequence is their plan for Wednesday.\n"
        "Plan:\n"
        "Acknowledge that ball machine work is much lower impact/intensity.\n"
        "Metric Check: TSB -5.92 is Productive.\n"
        "That changes things significantly! Hitting from a ball machine is much more controlled.\n"
        "Since the tennis will be lower intensity, your Wednesday multi-sport day looks much safer."
    )
    out = _extract_athlete_message_from_text(raw)
    assert out.startswith("That changes things significantly!")
    assert "Remind them" not in out
    assert "Ask if" not in out
    assert "Wait, the user's message" not in out
    assert "Plan:" not in out
    assert "Wednesday multi-sport day" in out


def test_calendar_preface_includes_named_weekday_dates():
    calendar = {
        "current_local_weekday": "Monday",
        "current_local_date": "2026-05-25",
        "tomorrow_weekday": "Tuesday",
        "tomorrow_date": "2026-05-26",
        "upcoming_weekdays": {
            "Monday": "2026-05-25",
            "Tuesday": "2026-05-26",
            "Wednesday": "2026-05-27",
        },
    }
    preface = _calendar_preface("This is all for Wednesday.", calendar)
    assert "Wednesday: 2026-05-27" in preface
    assert "preserve the previously discussed workout date" in preface


def test_normalize_schedule_date_from_named_weekday():
    calendar = {
        "current_local_date": "2026-05-25",
        "tomorrow_date": "2026-05-26",
        "upcoming_weekdays": {
            "Monday": "2026-05-25",
            "Tuesday": "2026-05-26",
            "Wednesday": "2026-05-27",
        },
    }
    out = _normalize_relative_tool_dates(
        "schedule_workout",
        {"date": "2026-05-26", "sport": "bike"},
        message="This is all for Wednesday.",
        calendar=calendar,
    )
    assert out["date"] == "2026-05-27"


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