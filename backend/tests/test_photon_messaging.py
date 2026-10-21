from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import coach as coach_router
from app.services import messaging, photon

ATHLETE = "athlete-1"
NUMBER = "+15551234567"
TOKEN = "bridge-secret"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def photon_settings(monkeypatch):
    monkeypatch.setattr(settings, "PHOTON_ATHLETE_ID", ATHLETE)
    monkeypatch.setattr(settings, "PHOTON_ALLOWED_NUMBER", NUMBER)
    monkeypatch.setattr(settings, "PHOTON_BRIDGE_TOKEN", TOKEN)
    messaging._inbound_times.clear()


# --- photon helpers --------------------------------------------------------

def test_normalize_number():
    assert photon.normalize_number("+1 (555) 123-4567") == NUMBER
    assert photon.normalize_number("5551234567") is None
    assert photon.normalize_number(None) is None


def test_is_allowed_sender():
    assert photon.is_allowed_sender("+1 555 123 4567")
    assert not photon.is_allowed_sender("+15559999999")
    assert not photon.is_allowed_sender(None)


def test_verify_bridge_token():
    assert photon.verify_bridge_token(TOKEN)
    assert not photon.verify_bridge_token("nope")
    assert not photon.verify_bridge_token(None)


def test_is_configured_requires_all_three(monkeypatch):
    assert photon.is_configured()
    monkeypatch.setattr(settings, "PHOTON_BRIDGE_TOKEN", None)
    assert not photon.is_configured()


# --- inbound router --------------------------------------------------------

def test_inbound_rejects_bad_token():
    res = TestClient(app).post(
        "/v1/messaging/photon/inbound",
        headers={"X-Photon-Bridge-Token": "wrong"},
        json={"message_id": "m1", "sender": NUMBER, "text": "hi"},
    )
    assert res.status_code == 401


def test_inbound_accepts_and_schedules():
    with patch.object(messaging, "handle_inbound_text", AsyncMock()) as handler:
        res = TestClient(app).post(
            "/v1/messaging/photon/inbound",
            headers={"X-Photon-Bridge-Token": TOKEN},
            json={"message_id": "m1", "sender": NUMBER, "text": "hi"},
        )
    assert res.status_code == 200
    handler.assert_awaited_once()
    assert handler.await_args.args[1:] == (NUMBER, "m1", "hi")


# --- handle_inbound_text ---------------------------------------------------

def test_inbound_from_stranger_is_dropped():
    with patch.object(messaging, "claim_inbound") as claim:
        assert _run(messaging.handle_inbound_text(MagicMock(), "+15559999999", "m1", "hi")) == "ignored_sender"
    claim.assert_not_called()


def test_inbound_duplicate_is_dropped():
    with patch.object(messaging, "claim_inbound", return_value=False):
        assert _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m1", "hi")) == "duplicate"


def test_inbound_runs_shared_coach_flow_with_text_sink():
    with patch.object(messaging, "claim_inbound", return_value=True), \
         patch.object(messaging, "get_or_create_conversation", return_value="conv-1"), \
         patch.object(coach_router, "_insert_message") as insert, \
         patch.object(coach_router, "_run_coach_response_and_notify", AsyncMock()) as run_coach:
        out = _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m1", "how was my ride?"))
    assert out == "processed"
    insert.assert_called_once()
    assert insert.call_args.args[1:5] == (ATHLETE, "conv-1", "user", "how was my ride?")
    args, kwargs = run_coach.await_args
    assert args[0] == ATHLETE and args[4] == "conv-1"
    assert "how was my ride?" in args[1] and "iMessage" in args[1]
    assert kwargs["reply_sink"] is photon.send_text


def test_new_command_opens_with_the_apps_greeting_and_stores_it():
    with patch.object(messaging, "claim_inbound", return_value=True),          patch.object(coach_router, "_create_conversation", return_value="conv-new") as create,          patch.object(coach_router, "_insert_message") as insert,          patch.object(coach_router, "_run_coach_response_and_notify", AsyncMock()) as run_coach,          patch("app.services.ai_coach.build_initialization_message", return_value=("Morning. HRV is down.", True)),          patch.object(photon, "send_text", AsyncMock()) as send:
        out = _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m1", "  /New "))
    assert out == "new_chat"
    assert create.call_args.args[1:] == (ATHLETE, None)
    assert insert.call_args.args[1:5] == (ATHLETE, "conv-new", "ai", "Morning. HRV is down.")
    send.assert_awaited_once_with("Morning. HRV is down.")
    run_coach.assert_not_awaited()


def test_new_command_falls_back_when_greeting_fails():
    with patch.object(messaging, "claim_inbound", return_value=True),          patch.object(coach_router, "_create_conversation", return_value="conv-new"),          patch.object(coach_router, "_insert_message") as insert,          patch("app.services.ai_coach.build_initialization_message", side_effect=RuntimeError("boom")),          patch.object(photon, "send_text", AsyncMock()) as send:
        assert _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m1", "/new")) == "new_chat"
    insert.assert_not_called()
    send.assert_awaited_once_with(messaging.NEW_CHAT_FALLBACK)


def test_inbound_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "PHOTON_MAX_INBOUND_PER_MINUTE", 1)
    with patch.object(messaging, "claim_inbound", return_value=True), \
         patch.object(messaging, "get_or_create_conversation", return_value="c"), \
         patch.object(coach_router, "_insert_message"), \
         patch.object(coach_router, "_run_coach_response_and_notify", AsyncMock()), \
         patch.object(photon, "send_text", AsyncMock()) as send:
        assert _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m1", "a")) == "processed"
        assert _run(messaging.handle_inbound_text(MagicMock(), NUMBER, "m2", "b")) == "rate_limited"
    send.assert_awaited_once()


# --- post-workout eligibility / claim -------------------------------------

def _row(**over):
    base = {
        "id": "w1",
        "sport": "rowing",
        "duration_seconds": 45 * 60,
        "ended_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "notified_at": None,
    }
    base.update(over)
    return base


def test_workout_eligible_happy_path():
    assert messaging._workout_eligible(_row())


def test_workout_window_is_twelve_hours():
    """Garmin watches often sync late, so a workout that ended hours ago still gets a text."""
    now = datetime.now(timezone.utc)
    assert messaging._workout_eligible(_row(ended_at=(now - timedelta(hours=11)).isoformat()))
    assert not messaging._workout_eligible(_row(ended_at=(now - timedelta(hours=13)).isoformat()))


@pytest.mark.parametrize(
    "over",
    [
        {"notified_at": "2026-10-20T00:00:00+00:00"},
        {"duration_seconds": 5 * 60},
        {"ended_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},
        {"ended_at": None},
    ],
)
def test_workout_ineligible(over):
    assert not messaging._workout_eligible(_row(**over))


def _db_returning(row):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [row]
    return db


def test_maybe_text_workout_sends_once_when_claim_won():
    with patch.object(messaging, "_claim_workout", return_value=True), \
         patch.object(messaging, "get_or_create_conversation", return_value="conv-1"), \
         patch.object(coach_router, "_insert_message") as insert, \
         patch("app.services.ai_coach.get_coach_response", return_value=("Solid piece.", [])), \
         patch.object(photon, "send_text", AsyncMock(return_value=True)) as send:
        assert _run(messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w1")) is True
    send.assert_awaited_once_with("Solid piece.")
    assert insert.call_args.args[3] == "ai"


def test_maybe_text_workout_skips_when_claim_lost():
    with patch.object(messaging, "_claim_workout", return_value=False), \
         patch.object(photon, "send_text", AsyncMock()) as send:
        assert _run(messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w1")) is False
    send.assert_not_awaited()


def test_maybe_text_workout_ignores_other_athletes():
    with patch.object(photon, "send_text", AsyncMock()) as send:
        assert _run(messaging.maybe_text_workout(MagicMock(), "someone-else", "w1")) is False
    send.assert_not_awaited()


def test_maybe_text_workout_releases_claim_if_coach_fails():
    with patch.object(messaging, "_claim_workout", return_value=True), \
         patch.object(messaging, "_release_workout") as release, \
         patch.object(messaging, "get_or_create_conversation", return_value="c"), \
         patch("app.services.ai_coach.get_coach_response", side_effect=RuntimeError("boom")), \
         patch.object(photon, "send_text", AsyncMock()) as send:
        assert _run(messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w1")) is False
    release.assert_called_once()
    send.assert_not_awaited()


def test_two_workouts_syncing_together_are_texted_one_at_a_time_in_order():
    events: list[str] = []

    def slow_coach(**kwargs):
        wid = re.search(r"workout id (\w+)", kwargs["message"]).group(1)
        events.append(f"start-{wid}")
        time.sleep(0.05)
        events.append(f"end-{wid}")
        return (f"note {wid}", [])

    async def send(text, to=None):
        events.append(f"sent-{text}")
        return True

    async def run_both():
        return await asyncio.gather(
            messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w1"),
            messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w2"),
        )

    with patch.object(messaging, "_claim_workout", return_value=True),          patch.object(messaging, "get_or_create_conversation", return_value="conv-1"),          patch.object(coach_router, "_insert_message"),          patch("app.services.ai_coach.get_coach_response", side_effect=slow_coach),          patch.object(photon, "send_text", side_effect=send):
        results = _run(run_both())

    assert results == [True, True]
    # The second coach call only starts after the first text has gone out.
    assert events == [
        "start-w1", "end-w1", "sent-note w1",
        "start-w2", "end-w2", "sent-note w2",
    ]


def test_maybe_text_workout_never_texts_the_coachs_canned_error_reply():
    from app.services.ai_coach import COACH_ERROR_REPLY, COACH_FAILURE_REPLIES

    for canned in COACH_FAILURE_REPLIES:
        with patch.object(messaging, "_claim_workout", return_value=True),              patch.object(messaging, "_release_workout") as release,              patch.object(messaging, "get_or_create_conversation", return_value="c"),              patch.object(coach_router, "_insert_message") as insert,              patch("app.services.ai_coach.get_coach_response", return_value=(canned, [])),              patch.object(photon, "send_text", AsyncMock()) as send:
            assert _run(messaging.maybe_text_workout(_db_returning(_row()), ATHLETE, "w1")) is False
        release.assert_called_once()  # claim is released so a later sync can retry
        insert.assert_not_called()
        send.assert_not_awaited()
    assert COACH_ERROR_REPLY in COACH_FAILURE_REPLIES
