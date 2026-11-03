from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import coach as coach_router
from app.services import coach_progress
from tests.conftest import MOCK_ATHLETE_ID


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _memory_backend():
    """Default every test to the in-process store (no Redis) with a clean slate."""
    coach_progress._memory.clear()
    with patch.object(coach_progress, "get_redis", return_value=None):
        yield
    coach_progress._memory.clear()


# ---------------------------------------------------------------------------
# In-process store
# ---------------------------------------------------------------------------


def test_append_and_read_in_order_with_timestamps():
    _run(coach_progress.append("ath", "conv", {"status": "started"}))
    _run(coach_progress.append("ath", "conv", {"status": "tool", "tool": "list_workouts"}))
    events = _run(coach_progress.read("ath", "conv"))
    assert [e["status"] for e in events] == ["started", "tool"]
    assert events[1]["tool"] == "list_workouts"
    assert all("at" in e for e in events)


def test_progress_is_scoped_by_athlete_and_conversation():
    _run(coach_progress.append("ath-a", "conv", {"status": "thinking"}))
    assert _run(coach_progress.read("ath-b", "conv")) == []
    assert _run(coach_progress.read("ath-a", "other")) == []


def test_reset_clears_previous_reply():
    _run(coach_progress.append("ath", "conv", {"status": "done"}))
    _run(coach_progress.reset("ath", "conv"))
    assert _run(coach_progress.read("ath", "conv")) == []


def test_keeps_only_the_most_recent_events():
    for i in range(coach_progress.MAX_EVENTS + 5):
        _run(coach_progress.append("ath", "conv", {"status": "thinking", "hop": i}))
    events = _run(coach_progress.read("ath", "conv"))
    assert len(events) == coach_progress.MAX_EVENTS
    assert events[-1]["hop"] == coach_progress.MAX_EVENTS + 4


def test_expired_entries_are_dropped():
    _run(coach_progress.append("ath", "conv", {"status": "thinking"}))
    key = coach_progress._key("ath", "conv")
    _, events = coach_progress._memory[key]
    coach_progress._memory[key] = (0.0, events)  # already expired
    assert _run(coach_progress.read("ath", "conv")) == []


# ---------------------------------------------------------------------------
# Redis-backed store
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.expiry: dict[str, int] = {}

    async def delete(self, key):
        self.lists.pop(key, None)

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start : end + 1]

    async def expire(self, key, ttl):
        self.expiry[key] = ttl

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))


def test_redis_backend_round_trip_and_ttl():
    redis = _FakeRedis()
    with patch.object(coach_progress, "get_redis", return_value=redis):
        _run(coach_progress.reset("ath", "conv"))
        _run(coach_progress.append("ath", "conv", {"status": "tool", "tool": "get_athlete_zones"}))
        events = _run(coach_progress.read("ath", "conv"))
    key = coach_progress._key("ath", "conv")
    assert events[0]["tool"] == "get_athlete_zones"
    assert redis.expiry[key] == coach_progress.PROGRESS_TTL_SEC
    assert json.loads(redis.lists[key][0])["status"] == "tool"


def test_redis_errors_fall_back_to_memory():
    broken = MagicMock()
    broken.rpush = AsyncMock(side_effect=ConnectionError("down"))
    broken.lrange = AsyncMock(side_effect=ConnectionError("down"))
    broken.delete = AsyncMock(side_effect=ConnectionError("down"))
    with patch.object(coach_progress, "get_redis", return_value=broken):
        _run(coach_progress.reset("ath", "conv"))
        _run(coach_progress.append("ath", "conv", {"status": "thinking"}))
        events = _run(coach_progress.read("ath", "conv"))
    assert [e["status"] for e in events] == ["thinking"]


def test_redis_read_skips_malformed_items():
    redis = _FakeRedis()
    key = coach_progress._key("ath", "conv")
    redis.lists[key] = ["not json", json.dumps({"status": "done"})]
    with patch.object(coach_progress, "get_redis", return_value=redis):
        events = _run(coach_progress.read("ath", "conv"))
    assert events == [{"status": "done"}]


# ---------------------------------------------------------------------------
# Background reply records the agentic loop's steps
# ---------------------------------------------------------------------------


def test_background_reply_records_tool_steps_then_done():
    def fake_get_coach_response(*_args, progress_callback=None, **_kwargs):
        progress_callback({"status": "context_ready"})
        progress_callback({"status": "tool", "tool": "list_workouts"})
        progress_callback({"status": "thinking", "hop": 1})
        return "Solid week.", []

    db = MagicMock()
    with patch.object(coach_router, "get_coach_response", side_effect=fake_get_coach_response), \
         patch.object(coach_router, "_insert_message"), \
         patch.object(coach_router, "_run_memory_extraction", AsyncMock()), \
         patch.object(coach_router, "_run_conversation_title", AsyncMock()), \
         patch("app.services.push.send_push_to_athlete"):
        _run(
            coach_router._run_coach_response_and_notify(
                "ath-1", "How was my week?", 40.0, db, "conv-1", "model-x", "model-y", 0
            )
        )
    events = _run(coach_progress.read("ath-1", "conv-1"))
    assert [e["status"] for e in events] == ["started", "context_ready", "tool", "thinking", "done"]
    assert events[2]["tool"] == "list_workouts"


# ---------------------------------------------------------------------------
# GET /v1/coach/conversations/{id}/progress
# ---------------------------------------------------------------------------


def test_progress_endpoint_returns_callers_events(coach_client):
    _run(coach_progress.append(MOCK_ATHLETE_ID, "conv-9", {"status": "tool", "tool": "get_workout_summary"}))
    res = coach_client.get("/v1/coach/conversations/conv-9/progress")
    assert res.status_code == 200
    events = res.json()["events"]
    assert events[0]["tool"] == "get_workout_summary"


def test_progress_endpoint_empty_when_nothing_running(coach_client):
    res = coach_client.get("/v1/coach/conversations/conv-none/progress")
    assert res.status_code == 200
    assert res.json() == {"events": []}
