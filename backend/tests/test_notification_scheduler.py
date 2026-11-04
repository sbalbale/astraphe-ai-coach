"""Timed notifications: when each one is due, and that a tick sends each once."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import notification_prefs as np
from app.services import notification_scheduler as ns


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi)


def test_window_after_the_chosen_time():
    assert ns.in_window(at(2026, 11, 3, 7, 0), "07:00")
    assert ns.in_window(at(2026, 11, 3, 7, 59), "07:00")
    assert not ns.in_window(at(2026, 11, 3, 8, 0), "07:00")
    assert not ns.in_window(at(2026, 11, 3, 6, 59), "07:00")


def test_weekly_on_the_chosen_day():
    sun = np.effective(None)
    mon = np.effective({"types": {"weekly": {"opt": "Mon"}}})
    assert ns.weekly_due(sun, at(2026, 11, 8, 18, 5))  # Sunday 18:05
    assert not ns.weekly_due(sun, at(2026, 11, 9, 7, 5))
    assert ns.weekly_due(mon, at(2026, 11, 9, 7, 5))  # Monday 07:05


def test_missed_checks_yesterday_in_the_morning_or_today_in_the_evening():
    morning = np.effective(None)
    evening = np.effective({"types": {"missed": {"opt": "evening"}}})
    assert ns.missed_check_day(morning, at(2026, 11, 4, 7, 10)) == date(2026, 11, 3)
    assert ns.missed_check_day(morning, at(2026, 11, 4, 12)) is None
    assert ns.missed_check_day(evening, at(2026, 11, 4, 20, 10)) == date(2026, 11, 4)


def test_key_sessions():
    assert ns.is_key_session({"primary_zone": "VO2Max", "target_tss": 60})
    assert ns.is_key_session({"primary_zone": "Endurance", "target_tss": 120})
    assert not ns.is_key_session({"primary_zone": "Endurance", "target_tss": 60})


def test_readiness_waits_for_sleep_except_at_the_end_of_the_window():
    assert ns.readiness_should_wait(at(2026, 11, 3, 7, 5), "07:00", has_score=False)
    assert not ns.readiness_should_wait(at(2026, 11, 3, 7, 52), "07:00", has_score=False)
    assert not ns.readiness_should_wait(at(2026, 11, 3, 7, 5), "07:00", has_score=True)


def test_weekly_covers_the_last_sunday_to_saturday_week():
    assert ns.last_completed_week_end(date(2026, 11, 8)) == date(2026, 11, 7)  # Sunday → Saturday before
    assert ns.last_completed_week_end(date(2026, 11, 9)) == date(2026, 11, 7)  # Monday → same week
    assert ns.last_completed_week_end(date(2026, 11, 7)) == date(2026, 10, 31)  # Saturday → the week before


def test_iso_week_key():
    assert ns.iso_week_key(date(2026, 11, 8)) == "2026-W45"


def test_tick_routes_by_local_time_and_respects_quiet_hours():
    athlete = {"id": "a1", "timezone_offset_min": -300, "notification_settings": None}
    calls = []
    with patch.object(ns, "send_held_debriefs", side_effect=lambda *a, **k: calls.append("held")), patch.object(
        ns, "send_readiness", side_effect=lambda *a, **k: calls.append("ready")
    ), patch.object(ns, "send_missed", side_effect=lambda *a, **k: calls.append("missed")), patch.object(
        ns, "send_weekly", side_effect=lambda *a, **k: calls.append("weekly")
    ), patch.object(ns, "send_sync_problem", side_effect=lambda *a, **k: calls.append("sync")):
        # 12:05 UTC = 07:05 in UTC-5 on Tuesday: readiness + missed (morning) are due.
        ns.tick_athlete(MagicMock(), athlete, datetime(2026, 11, 3, 12, 5, tzinfo=timezone.utc))
        assert calls == ["held", "ready", "missed"]
        calls.clear()
        # 04:00 UTC = 23:00 local: quiet hours, nothing due.
        ns.tick_athlete(MagicMock(), athlete, datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc))
        assert calls == []


def test_held_debriefs_are_pushed_once_with_a_digest():
    db = MagicMock()
    q = db.table.return_value.select.return_value
    q.eq.return_value.eq.return_value.eq.return_value.gte.return_value.not_.is_.return_value.order.return_value.execute.return_value.data = [
        {"id": "l1", "conversation_id": "c1"},
        {"id": "l2", "conversation_id": "c2"},
    ]
    q.eq.return_value.limit.return_value.execute.return_value.data = [{"title": "x", "context": {"title": "River loop"}}]
    q.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"content": "Nice."}]
    prefs = np.effective({"types": {"debrief": {"opt": "evening"}}})
    with patch.object(ns.cn, "claim", return_value="d1"), patch.object(ns.cn, "push_thread", return_value=True) as push, patch.object(
        ns.cn, "mark_log"
    ) as mark:
        ns.send_held_debriefs(db, "a1", prefs, at(2026, 11, 3, 19, 5))
    kw = push.call_args.kwargs
    assert kw["conversation_id"] == "c2" and kw["title"] == "Coach · 2 workout debriefs" and kw["ignore_timing"]
    assert [c.args[0] for c in mark.call_args_list] == ["l1", "l2"]
    # Not 19:00 yet for the evening digest: nothing.
    with patch.object(ns.cn, "push_thread") as push:
        ns.send_held_debriefs(db, "a1", prefs, at(2026, 11, 3, 15))
    push.assert_not_called()
