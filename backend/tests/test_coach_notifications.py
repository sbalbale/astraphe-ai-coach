"""Notification settings and the post-workout debrief (coach thread + push)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services import coach_notifications as cn
from app.services import notification_prefs as np


# --- settings ----------------------------------------------------------------------------

def test_defaults_and_legacy_flags():
    p = np.effective(None)
    assert p["types"]["debrief"] == {"on": True, "opt": "now", "push": True}
    assert p["quiet"] == {"on": True, "from": "22:00", "to": "07:00"}
    # Old flat keys still switch the matching types off.
    p = np.effective({"readiness": False, "coach": False})
    assert not p["types"]["ready"]["on"] and not p["types"]["debrief"]["on"] and not p["types"]["plan"]["on"]
    assert p["types"]["weekly"]["on"]


def test_bad_values_are_ignored():
    p = np.effective({"types": {"ready": {"opt": "03:00", "on": "yes"}, "nope": {"on": False}}, "quiet": {"from": "25:99"}, "texts": "loud"})
    assert p["types"]["ready"]["opt"] == "07:00" and p["types"]["ready"]["on"] is True
    assert "nope" not in p["types"]
    assert p["quiet"]["from"] == "22:00" and p["texts"] == "active"


def test_quiet_hours_wrap_midnight():
    p = np.effective({"quiet": {"on": True, "from": "22:00", "to": "07:00"}})
    at = lambda h, m=0: datetime(2026, 11, 3, h, m)
    assert np.in_quiet_hours(p, at(23)) and np.in_quiet_hours(p, at(6, 59))
    assert not np.in_quiet_hours(p, at(7)) and not np.in_quiet_hours(p, at(21, 59))
    assert not np.in_quiet_hours(np.effective({"quiet": {"on": False}}), at(23))


def test_legacy_type_names_still_gate_pushes():
    assert np.legacy_type_enabled({"coach": False}, "coach") is False
    assert np.legacy_type_enabled({}, "coach") is True
    assert np.legacy_type_enabled({"types": {"ready": {"on": False}}}, "ready") is False


# --- debrief -----------------------------------------------------------------------------

def _workout(**kw):
    now = datetime.now(timezone.utc)
    return {"id": "w1", "sport": "bike", "title": "Farmington River loop", "started_at": (now - timedelta(hours=2)).isoformat(),
            "ended_at": (now - timedelta(minutes=30)).isoformat(), "duration_seconds": 5100, "tss": 92, "notified_at": None, **kw}


def test_debrief_eligibility():
    assert cn.debrief_eligible(_workout())
    assert not cn.debrief_eligible(_workout(duration_seconds=300))  # too short
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert not cn.debrief_eligible(_workout(ended_at=old, started_at=old))  # history backfill


def _db_with(rows):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = rows
    return db


def _run(coro):
    return asyncio.run(coro)


def test_debrief_creates_a_thread_and_pushes_it():
    prefs = np.effective(None)
    with patch.object(cn, "load_prefs", return_value=prefs), patch.object(cn, "claim", return_value="log-1"), patch.object(
        cn, "workout_context", return_value={"kind": "workout", "id": "w1", "title": "Farmington River loop", "meta": "Mon 2 Nov · 1h 25"}
    ), patch.object(cn, "_compose_debrief", return_value="Solid work: all three blocks in range. How did the legs feel?"), patch.object(
        cn, "create_coach_thread", return_value="conv-1"
    ) as mk, patch.object(cn, "push_thread", return_value=True) as push, patch.object(cn, "mark_log") as mark, patch.object(
        cn, "admin_db"
    ), patch.object(cn, "_photon_configured", return_value=False):
        cid = _run(cn.post_workout_debrief(_db_with([_workout()]), "ath-1", "w1"))
    assert cid == "conv-1"
    kw = mk.call_args.kwargs
    assert kw["trigger"] == "debrief" and kw["title"] == "Farmington River loop debrief"
    assert kw["quick_replies"] == cn.DEBRIEF_QUICK_REPLIES
    assert push.call_args.kwargs["title"] == "Coach · Farmington River loop"
    assert push.call_args.kwargs["body"].startswith("Solid work")
    mark.assert_called_once_with("log-1", conversation_id="conv-1", pushed=True)


def test_debrief_runs_once_per_workout():
    with patch.object(cn, "load_prefs", return_value=np.effective(None)), patch.object(cn, "claim", return_value=None), patch.object(
        cn, "_compose_debrief"
    ) as compose, patch.object(cn, "_photon_configured", return_value=False):
        assert _run(cn.post_workout_debrief(_db_with([_workout()]), "ath-1", "w1")) is None
    compose.assert_not_called()


def test_failed_note_releases_the_claim_for_a_retry():
    with patch.object(cn, "load_prefs", return_value=np.effective(None)), patch.object(cn, "claim", return_value="log-1"), patch.object(
        cn, "workout_context", return_value={"title": "Ride"}
    ), patch.object(cn, "_compose_debrief", return_value=None), patch.object(cn, "release") as release, patch.object(
        cn, "create_coach_thread"
    ) as mk, patch.object(cn, "_photon_configured", return_value=False):
        assert _run(cn.post_workout_debrief(_db_with([_workout()]), "ath-1", "w1")) is None
    release.assert_called_once_with("log-1")
    mk.assert_not_called()


def test_debrief_off_and_texts_off_does_nothing():
    prefs = np.effective({"types": {"debrief": {"on": False}}, "texts": "off"})
    with patch.object(cn, "load_prefs", return_value=prefs), patch.object(cn, "claim") as claim:
        assert _run(cn.post_workout_debrief(MagicMock(), "ath-1", "w1")) is None
    claim.assert_not_called()


def test_push_thread_respects_type_quiet_hours_and_digest():
    prefs = np.effective({"quiet": {"on": False}})
    with patch.object(cn, "local_now", return_value=datetime(2026, 11, 3, 12)), patch.object(cn, "admin_db"), patch(
        "app.services.push.send_push_to_athlete", return_value=1
    ) as send:
        assert cn.push_thread(MagicMock(), "a", type_id="debrief", conversation_id="c", title="t", body="b", prefs=prefs)
        assert send.call_args.kwargs["data"]["url"] == "/chat?conversation=c"
        evening = np.effective({"quiet": {"on": False}, "types": {"debrief": {"opt": "evening"}}})
        assert not cn.push_thread(MagicMock(), "a", type_id="debrief", conversation_id="c", title="t", body="b", prefs=evening)
        off = np.effective({"types": {"weekly": {"on": False}}})
        assert not cn.push_thread(MagicMock(), "a", type_id="weekly", conversation_id="c", title="t", body="b", prefs=off)
    with patch.object(cn, "local_now", return_value=datetime(2026, 11, 3, 23)):
        assert not cn.push_thread(MagicMock(), "a", type_id="debrief", conversation_id="c", title="t", body="b", prefs=np.effective(None))


def test_profile_accepts_and_normalizes_v2_notification_settings():
    import pytest
    from pydantic import ValidationError

    from app.models.athlete import AthleteProfileUpdate

    p = AthleteProfileUpdate(notification_settings={"v": 2, "types": {"ready": {"on": False, "opt": "06:30"}, "bogus": {}}, "quiet": {"on": True, "from": "23:00", "to": "06:00"}, "texts": "off", "junk": 1})
    ns = p.notification_settings
    assert ns["types"]["ready"] == {"on": False, "opt": "06:30", "push": True}
    assert "bogus" not in ns["types"] and "junk" not in ns
    assert ns["quiet"] == {"on": True, "from": "23:00", "to": "06:00"} and ns["texts"] == "off"
    with pytest.raises(ValidationError):
        AthleteProfileUpdate(notification_settings={"types": {"debrief": {"x": "y" * 5000}}})
