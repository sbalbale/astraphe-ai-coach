"""Tests for coach SSE streaming keepalive and progress events."""
from __future__ import annotations

import asyncio
import json
import time

from app.routers import coach as coach_router


async def _collect_stream_events(monkeypatch) -> list[dict]:
    monkeypatch.setattr(coach_router, "_COACH_STREAM_KEEPALIVE_SEC", 0.05)

    def slow_get(*_args, progress_callback=None, **_kwargs):
        time.sleep(0.12)
        if progress_callback:
            progress_callback({"status": "thinking", "hop": 0})
        time.sleep(0.12)
        return ("Athlete reply", [{"title": "src", "url": "https://example.com"}])

    monkeypatch.setattr(coach_router, "get_coach_response", slow_get)

    events: list[dict] = []
    async for event in coach_router._stream_coach_agentic(
        athlete_id="athlete-1",
        effective_message="plan my week",
        recent_tss=0.0,
        db=None,
        conversation_id="conv-1",
        model_name="test-model",
        timezone_offset_min=0,
    ):
        events.append(event)
    return events


def test_stream_coach_agentic_emits_keepalive_and_progress(monkeypatch):
    events = asyncio.run(_collect_stream_events(monkeypatch))
    assert any(e.get("_keepalive") for e in events)
    assert any(e.get("status") == "thinking" for e in events)
    assert events[-1]["_result"][0] == "Athlete reply"


def test_coach_stream_endpoint_started_status(coach_client, monkeypatch):
    def fast_get(*_args, progress_callback=None, **_kwargs):
        if progress_callback:
            progress_callback({"status": "context_ready"})
        return ("Done.", [])

    monkeypatch.setattr(coach_router, "get_coach_response", fast_get)

    payloads: list[dict] = []
    with coach_client.stream(
        "POST",
        "/v1/coach/stream",
        json={
            "message": "How should I train?",
            "recent_tss": 50,
            "conversation_id": "fake-conversation-id",
        },
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("cache-control") == "no-cache"
        buffer = ""
        for chunk in resp.iter_bytes():
            buffer += chunk.decode("utf-8")
            while "\n\n" in buffer:
                part, buffer = buffer.split("\n\n", 1)
                for line in part.split("\n"):
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if raw and raw != "[DONE]":
                            payloads.append(json.loads(raw))

    assert payloads[0]["status"] == "started"
    assert payloads[0]["conversation_id"] == "fake-conversation-id"
    assert any(p.get("status") == "context_ready" for p in payloads)
    assert any("text" in p for p in payloads)
