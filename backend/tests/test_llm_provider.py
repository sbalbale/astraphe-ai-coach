from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.genai import types

from app.config import settings
from app.services import llm_provider


# ---------------------------------------------------------------------------
# Tool schema translation
# ---------------------------------------------------------------------------

def test_gemini_tools_to_openai_lowercases_schema_types_and_preserves_shape():
    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_weather",
            description="Get current weather",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "city": types.Schema(type=types.Type.STRING),
                    "days": types.Schema(type=types.Type.INTEGER),
                },
                required=["city"],
            ),
        )
    ])
    out = llm_provider._gemini_tools_to_openai([tool])
    assert out == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": ["city"],
            },
        },
    }]


def test_gemini_tools_to_openai_drops_non_function_tools():
    """google_search (Gemini-proprietary grounding) has no OpenAI equivalent."""
    tools = [
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(function_declarations=[
            types.FunctionDeclaration(name="noop", parameters=types.Schema(type=types.Type.OBJECT))
        ]),
    ]
    out = llm_provider._gemini_tools_to_openai(tools)
    assert len(out) == 1
    assert out[0]["function"]["name"] == "noop"


def test_gemini_tools_to_openai_none_input():
    assert llm_provider._gemini_tools_to_openai(None) is None
    assert llm_provider._gemini_tools_to_openai([]) is None


# ---------------------------------------------------------------------------
# Message translation
# ---------------------------------------------------------------------------

def test_contents_to_messages_plain_string_with_system_instruction():
    msgs = llm_provider._gemini_contents_to_openai_messages("hello", "be nice")
    assert msgs == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hello"},
    ]


def test_contents_to_messages_multi_hop_tool_call_round_trip():
    """Mirrors exactly what ai_coach.py's agentic loop builds: a user turn,
    a model turn with a function_call, then a user turn with the matching
    function_response — the tool_call_id pairing must line up."""
    fc = types.FunctionCall(name="get_athlete_zones", args={})
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text="what are my zones?")]),
        types.Content(role="model", parts=[types.Part(function_call=fc)]),
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name="get_athlete_zones", response={"z1": "100-120"})],
        ),
    ]
    msgs = llm_provider._gemini_contents_to_openai_messages(contents, None)
    assert msgs[0] == {"role": "user", "content": "what are my zones?"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["tool_calls"][0]["function"]["name"] == "get_athlete_zones"
    call_id = msgs[1]["tool_calls"][0]["id"]
    assert msgs[2] == {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps({"z1": "100-120"}),
    }


# ---------------------------------------------------------------------------
# Response wrapping
# ---------------------------------------------------------------------------

def _fake_completion(*, content=None, reasoning_content=None, tool_calls=None):
    message = SimpleNamespace(content=content, reasoning_content=reasoning_content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_wrap_chat_completion_plain_text():
    resp = llm_provider._wrap_chat_completion(_fake_completion(content="hi there"))
    assert resp.text == "hi there"
    parts = resp.candidates[0].content.parts
    assert len(parts) == 1
    assert parts[0].text == "hi there"
    assert parts[0].thought is False


def test_wrap_chat_completion_reasoning_becomes_thought_part():
    resp = llm_provider._wrap_chat_completion(
        _fake_completion(content="final answer", reasoning_content="scratch work")
    )
    parts = resp.candidates[0].content.parts
    thought_parts = [p for p in parts if p.thought]
    text_parts = [p for p in parts if not p.thought and p.text]
    assert thought_parts and thought_parts[0].text == "scratch work"
    assert text_parts and text_parts[0].text == "final answer"
    assert resp.text == "final answer"


def test_wrap_chat_completion_tool_calls():
    tc = SimpleNamespace(
        function=SimpleNamespace(name="schedule_workout", arguments='{"date": "2026-08-10"}')
    )
    resp = llm_provider._wrap_chat_completion(_fake_completion(content=None, tool_calls=[tc]))
    parts = resp.candidates[0].content.parts
    fcs = [p.function_call for p in parts if p.function_call]
    assert len(fcs) == 1
    assert fcs[0].name == "schedule_workout"
    assert fcs[0].args == {"date": "2026-08-10"}


def test_wrap_chat_completion_malformed_tool_call_arguments_falls_back_to_empty_dict():
    tc = SimpleNamespace(function=SimpleNamespace(name="schedule_workout", arguments="{not json"))
    resp = llm_provider._wrap_chat_completion(_fake_completion(content=None, tool_calls=[tc]))
    fcs = [p.function_call for p in resp.candidates[0].content.parts if p.function_call]
    assert fcs[0].args == {}


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def test_get_llm_client_defaults_to_gemini(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    llm_provider.get_llm_client.cache_clear()
    client = llm_provider.get_llm_client()
    assert type(client).__module__.startswith("google.genai")
    llm_provider.get_llm_client.cache_clear()


def test_get_llm_client_openai_requires_base_url(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_BASE_URL", None)
    llm_provider.get_llm_client.cache_clear()
    with pytest.raises(RuntimeError, match="OPENAI_API_BASE_URL"):
        llm_provider.get_llm_client()
    llm_provider.get_llm_client.cache_clear()


def test_get_llm_client_openai_returns_shim(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_BASE_URL", "http://localhost:8080/v1")
    llm_provider.get_llm_client.cache_clear()
    client = llm_provider.get_llm_client()
    assert isinstance(client, llm_provider._OpenAICompatClient)
    llm_provider.get_llm_client.cache_clear()
