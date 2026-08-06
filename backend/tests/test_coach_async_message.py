from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.dependencies import UserConfig, get_user_config, get_user_db
from app.main import app
from app.routers import coach as coach_router
from app.services.gemini_quota import GeminiQuotaExceededError


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# POST /v1/coach/message/async
# ---------------------------------------------------------------------------


def test_submit_coach_message_new_conversation_schedules_background_task(coach_client, fake_db):
    with patch.object(coach_router, "_run_coach_response_and_notify", AsyncMock()):
        res = coach_client.post("/v1/coach/message/async", json={"message": "How was my ride?"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["conversation_id"]


def test_submit_coach_message_reuses_existing_conversation_id(coach_client, fake_db):
    fake_db._table_seeds["coach_conversations"] = [
        {"id": "conv-1", "athlete_id": None, "title": "Existing"}
    ]
    with patch.object(coach_router, "_run_coach_response_and_notify", AsyncMock()):
        res = coach_client.post(
            "/v1/coach/message/async", json={"conversation_id": "conv-1", "message": "Follow up"}
        )
    assert res.status_code == 200
    assert res.json()["conversation_id"] == "conv-1"


def test_submit_coach_message_with_document_contents_builds_effective_message(coach_client, fake_db):
    captured = {}

    async def _fake_notify(athlete_id, effective_message, *args, **kwargs):
        captured["effective_message"] = effective_message

    with patch.object(coach_router, "_run_coach_response_and_notify", _fake_notify):
        res = coach_client.post(
            "/v1/coach/message/async",
            json={"message": "Summarize this", "document_contents": ["Doc body text"]},
        )
    assert res.status_code == 200
    assert "[ATTACHED DOCUMENT 1]" in captured["effective_message"]
    assert "Doc body text" in captured["effective_message"]
    assert "[ATHLETE MESSAGE]\nSummarize this" in captured["effective_message"]


def test_submit_coach_message_non_premium_returns_403(client, fake_db):
    free_config = UserConfig(
        user_id="u1", tier="free", gemini_model="m", gemini_analysis_model="m2",
        rate_limit_rpm=5, rate_limit_rph=20, is_admin=False,
    )
    app.dependency_overrides[get_user_config] = lambda: free_config
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        res = client.post("/v1/coach/message/async", json={"message": "hi"})
    finally:
        app.dependency_overrides.pop(get_user_config, None)
        app.dependency_overrides.pop(get_user_db, None)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# _run_coach_response_and_notify (direct unit tests)
# ---------------------------------------------------------------------------


def test_run_coach_response_and_notify_success_full_flow():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", return_value=("Great ride!", [{"url": "https://x.com"}])
    ), patch.object(coach_router, "_insert_message") as mock_insert, patch.object(
        coach_router, "_load_conversation_history", return_value=[{"role": "user", "content": "hi"}]
    ), patch.object(
        coach_router, "_run_memory_extraction", AsyncMock()
    ) as mock_memory, patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ) as mock_title, patch(
        "app.services.push.send_push_to_athlete"
    ) as mock_push:
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "How was my ride?", 50.0, db, "conv-1", "model-x", "model-y", 0
            )
        )
    mock_insert.assert_called_once()
    assert mock_insert.call_args.kwargs["content"] == "Great ride!"
    mock_memory.assert_awaited_once()
    mock_title.assert_awaited_once()
    mock_push.assert_called_once()


def test_run_coach_response_and_notify_quota_exceeded_uses_friendly_message():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", side_effect=GeminiQuotaExceededError("gemma-4-31b-it", 125.0)
    ), patch.object(coach_router, "_insert_message") as mock_insert, patch.object(
        coach_router, "_load_conversation_history", return_value=[]
    ), patch.object(coach_router, "_run_memory_extraction", AsyncMock()), patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ), patch("app.services.push.send_push_to_athlete"):
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "hi", 0.0, db, "conv-1", None, None, None
            )
        )
    reply = mock_insert.call_args.kwargs["content"]
    assert "request limit" in reply
    assert "2 minute" in reply  # round(125/60) = 2, pluralized


def test_run_coach_response_and_notify_generic_error_uses_fallback_message():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", side_effect=RuntimeError("gemini exploded")
    ), patch.object(coach_router, "_insert_message") as mock_insert, patch.object(
        coach_router, "_load_conversation_history", return_value=[]
    ), patch.object(coach_router, "_run_memory_extraction", AsyncMock()), patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ), patch("app.services.push.send_push_to_athlete"):
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "hi", 0.0, db, "conv-1", None, None, None
            )
        )
    reply = mock_insert.call_args.kwargs["content"]
    assert "ran into an error" in reply


def test_run_coach_response_and_notify_insert_failure_returns_early():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", return_value=("reply", [])
    ), patch.object(
        coach_router, "_insert_message", side_effect=RuntimeError("db down")
    ), patch.object(
        coach_router, "_run_memory_extraction", AsyncMock()
    ) as mock_memory, patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ) as mock_title:
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "hi", 0.0, db, "conv-1", None, None, None
            )
        )
    mock_memory.assert_not_awaited()
    mock_title.assert_not_awaited()


def test_run_coach_response_and_notify_memory_extraction_failure_is_swallowed():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", return_value=("reply", [])
    ), patch.object(coach_router, "_insert_message"), patch.object(
        coach_router, "_load_conversation_history", side_effect=RuntimeError("history load failed")
    ), patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ) as mock_title, patch("app.services.push.send_push_to_athlete"):
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "hi", 0.0, db, "conv-1", None, None, None
            )
        )
    mock_title.assert_awaited_once()  # still runs despite memory extraction failing


def test_run_coach_response_and_notify_push_failure_is_swallowed():
    db = MagicMock()
    with patch.object(
        coach_router, "get_coach_response", return_value=("reply", [])
    ), patch.object(coach_router, "_insert_message"), patch.object(
        coach_router, "_load_conversation_history", return_value=[]
    ), patch.object(coach_router, "_run_memory_extraction", AsyncMock()), patch.object(
        coach_router, "_run_conversation_title", AsyncMock()
    ), patch("app.services.push.send_push_to_athlete", side_effect=RuntimeError("push failed")):
        # should not raise
        _run_async(
            coach_router._run_coach_response_and_notify(
                "ath-1", "hi", 0.0, db, "conv-1", None, None, None
            )
        )
