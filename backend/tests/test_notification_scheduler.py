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


def test_missed_only_checks_a_day_that_is_over():
    morning = np.effective(None)
    evening = np.effective({"types": {"missed": {"opt": "evening"}}})
    assert ns.missed_check_day(morning, at(2026, 11, 4, 7, 10)) == date(2026, 11, 3)
    assert ns.missed_check_day(morning, at(2026, 11, 4, 12)) is None
    # Evening: yesterday's session, never today's (an evening session may still happen).
    assert ns.missed_check_day(evening, at(2026, 11, 4, 20, 10)) == date(2026, 11, 3)
    assert ns.missed_check_day(evening, at(2026, 11, 4, 7, 10)) is None


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


# --- a small filtering fake of the Supabase query builder ---------------------------------

class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self._range, self._limit, self._order = db, name, [], None, None, None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def in_(self, k, vs):
        self.db.in_calls.append((self.name, list(vs)))
        self.filters.append(lambda r: r.get(k) in vs)
        return self

    def gte(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) >= str(v))
        return self

    def gt(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) > str(v))
        return self

    def lt(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) < str(v))
        return self

    def lte(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) <= str(v))
        return self

    def order(self, k, desc=False):
        self._order = (k, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        rows = [r for r in self.db.rows.get(self.name, []) if all(f(r) for f in self.filters)]
        if self._order:
            rows.sort(key=lambda r: str(r.get(self._order[0])), reverse=self._order[1])
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit:
            rows = rows[: self._limit]
        return MagicMock(data=rows)


class _Db:
    def __init__(self, **rows):
        self.rows, self.in_calls = rows, []

    def table(self, name):
        return _Q(self, name)


def _claims():
    """cn.claim / cn.release backed by a set, like the unique notification_log key."""
    held: dict = {}

    def claim(aid, kind, key):
        if (kind, key) in held.values():
            return None
        log_id = f"log-{len(held) + 1}-{kind}"
        held[log_id] = (kind, key)
        return log_id

    def release(log_id):
        held.pop(log_id, None)

    return claim, release


# --- held debriefs look back past the previous digest window ------------------------------

def test_held_debriefs_look_back_36_hours_from_the_tick_time():
    now = datetime(2026, 11, 4, 0, 5, tzinfo=timezone.utc)  # 19:05 in UTC-5
    db = MagicMock()
    q = db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    q.gte.return_value.not_.is_.return_value.order.return_value.execute.return_value.data = []
    prefs = np.effective({"types": {"debrief": {"opt": "evening"}}})
    ns.send_held_debriefs(db, "a1", prefs, at(2026, 11, 3, 19, 5), now)
    since = q.gte.call_args.args[1]
    # Covers yesterday's 20:30 local workout (01:30 UTC on the 3rd), after yesterday's window.
    assert since == "2026-11-02T12:05:00+00:00" and since < "2026-11-03T01:30:00+00:00"


# --- missed key session ------------------------------------------------------------------

_PLAN = {"id": "p1", "athlete_id": "a1", "title": "VO2 intervals", "planned_date": "2026-11-03", "target_tss": 90,
         "primary_zone": "VO2Max", "status": "planned", "sport": "bike", "duration_min": 60}


def _missed(workouts, plan=_PLAN):
    """True when the session would be claimed as missed."""
    db = _Db(training_plans=[plan], workouts=[{"athlete_id": "a1", **w} for w in workouts])
    with patch.object(ns.cn, "claim", return_value=None) as claim:
        ns.send_missed(db, "a1", np.effective(None), date(2026, 11, 3), at(2026, 11, 4, 7, 5), -300)
    return claim.called


def test_missed_skips_a_session_done_but_not_linked():
    # 23:30 local on the day (04:30 UTC the next day) in UTC-5, same sport.
    assert not _missed([{"sport": "bike", "duration_seconds": 1200, "started_at": "2026-11-04T04:30:00+00:00"}])
    # The next local day counts too, with the sport normalized.
    assert not _missed([{"sport": "cycling", "duration_seconds": 1200, "started_at": "2026-11-04T10:00:00+00:00"}])
    # A long 'other' workout (rowing often syncs that way) counts; a short one doesn't.
    assert not _missed([{"sport": "other", "duration_seconds": 1800, "started_at": "2026-11-03T15:00:00+00:00"}])
    assert _missed([{"sport": "other", "duration_seconds": 900, "started_at": "2026-11-03T15:00:00+00:00"}])
    # Unknown planned sport: any long workout counts.
    assert not _missed([{"sport": "run", "duration_seconds": 2400, "started_at": "2026-11-03T15:00:00+00:00"}], {**_PLAN, "sport": None})
    # Different sport, or outside the two local days: still missed.
    assert _missed([{"sport": "run", "duration_seconds": 3600, "started_at": "2026-11-03T15:00:00+00:00"}])
    assert _missed([{"sport": "bike", "duration_seconds": 3600, "started_at": "2026-11-03T04:00:00+00:00"}])  # 23:00 the day before
    assert _missed([])


def test_missed_compose_failure_retries_once_then_keeps_the_claim():
    db = _Db(training_plans=[_PLAN], workouts=[])
    claim, release = _claims()
    with patch.object(ns.cn, "claim", side_effect=claim), patch.object(ns.cn, "release", side_effect=release), patch.object(
        ns, "_compose", return_value=None
    ) as compose, patch.object(ns.cn, "create_coach_thread") as mk:
        for _ in range(5):
            ns.send_missed(db, "a1", np.effective(None), date(2026, 11, 3), at(2026, 11, 4, 7, 5), -300)
    assert compose.call_count == 2
    mk.assert_not_called()


def test_weekly_compose_failure_retries_once():
    claim, release = _claims()
    with patch.object(ns.cn, "claim", side_effect=claim), patch.object(ns.cn, "release", side_effect=release), patch.object(
        ns, "_compose", return_value=None
    ) as compose:
        for _ in range(4):
            ns.send_weekly(_Db(), "a1", np.effective(None), at(2026, 11, 8, 18, 5))
    assert compose.call_count == 2


# --- quiet hours: claimed only outside them, and the window still has a free tick -----------

def test_missed_and_weekly_wait_for_quiet_hours_to_end():
    late_quiet = {"quiet": {"on": True, "from": "22:00", "to": "07:30"}}
    athlete = {"id": "a1", "timezone_offset_min": 0, "notification_settings": late_quiet}
    calls = []
    with patch.object(ns, "send_held_debriefs"), patch.object(ns, "send_readiness"), patch.object(
        ns, "send_missed", side_effect=lambda *a, **k: calls.append("missed")
    ), patch.object(ns, "send_sync_problem"):
        ns.tick_athlete(MagicMock(), athlete, datetime(2026, 11, 4, 7, 5, tzinfo=timezone.utc))
        assert calls == []  # quiet until 07:30: not claimed
        ns.tick_athlete(MagicMock(), athlete, datetime(2026, 11, 4, 7, 35, tzinfo=timezone.utc))
        assert calls == ["missed"]
    sunday = {"id": "a1", "timezone_offset_min": 0, "notification_settings": {"quiet": {"on": True, "from": "17:00", "to": "19:00"}}}
    calls.clear()
    with patch.object(ns, "send_held_debriefs"), patch.object(ns, "send_weekly", side_effect=lambda *a, **k: calls.append("weekly")):
        ns.tick_athlete(MagicMock(), sunday, datetime(2026, 11, 8, 18, 5, tzinfo=timezone.utc))
        assert calls == []
        ns.tick_athlete(MagicMock(), sunday, datetime(2026, 11, 8, 19, 5, tzinfo=timezone.utc))
        assert calls == ["weekly"]


def test_default_quiet_hours_leave_free_ticks_in_every_window():
    prefs = np.effective(None)
    for opt in ("morning", "evening"):
        p = np.effective({"types": {"missed": {"opt": opt}}})
        start = 7 if opt == "morning" else 20
        ticks = [at(2026, 11, 4, start, m) for m in range(0, 60, 5)]
        assert any(ns.missed_check_day(p, t) and not np.in_quiet_hours(prefs, t) for t in ticks)
    for opt, d, h in (("Sun", 8, 18), ("Mon", 9, 7)):
        p = np.effective({"types": {"weekly": {"opt": opt}}})
        ticks = [at(2026, 11, d, h, m) for m in range(0, 60, 5)]
        assert any(ns.weekly_due(p, t) and not np.in_quiet_hours(prefs, t) for t in ticks)


# --- sync problems -------------------------------------------------------------------------

def _sync_db(providers, log=(), workouts=()):
    return _Db(
        oauth_tokens=[{"athlete_id": "a1", "provider": p} for p in providers],
        workouts=[{"athlete_id": "a1", "started_at": s} for s in workouts],
        biometrics=[],
        notification_log=[{"athlete_id": "a1", "kind": "sync", "created_at": c} for c in log],
    )


def test_sync_alerts_skip_strava_and_stop_after_three():
    now = datetime(2026, 11, 20, 14, 5, tzinfo=timezone.utc)
    local = at(2026, 11, 20, 9, 5)
    last = ["2026-11-01T10:00:00+00:00"]
    with patch.object(ns.cn, "claim", return_value="s1"), patch("app.services.push.send_push_to_athlete") as send:
        ns.send_sync_problem(_sync_db(["strava"], workouts=last), "a1", local, now)
        send.assert_not_called()
        ns.send_sync_problem(_sync_db(["garmin", "strava"], workouts=last), "a1", local, now)
        assert send.call_args.kwargs["title"] == "Garmin stopped sending data"
        send.reset_mock()
        # Three alerts already sent for this outage: silence.
        three = ["2026-11-04T14:00:00+00:00", "2026-11-07T14:00:00+00:00", "2026-11-13T14:00:00+00:00"]
        ns.send_sync_problem(_sync_db(["garmin"], log=three, workouts=last), "a1", local, now)
        send.assert_not_called()
        # Alerts from before the last data belong to an earlier outage.
        ns.send_sync_problem(_sync_db(["garmin"], log=three, workouts=["2026-11-15T10:00:00+00:00"]), "a1", local, now)
        send.assert_called_once()
        send.reset_mock()
        # Data within 48 hours: no problem.
        ns.send_sync_problem(_sync_db(["garmin"], workouts=["2026-11-19T10:00:00+00:00"]), "a1", local, now)
        send.assert_not_called()


def test_sync_alerts_back_off():
    now = datetime(2026, 11, 20, 14, 5, tzinfo=timezone.utc)
    d = lambda day: datetime(2026, 11, day, 14, 0, tzinfo=timezone.utc)
    assert ns.sync_alert_due([], now)
    assert not ns.sync_alert_due([d(18)], now)
    assert ns.sync_alert_due([d(17)], now)
    assert not ns.sync_alert_due([d(10), d(16)], now)  # second gap is 6 days
    assert ns.sync_alert_due([d(10), d(14)], now)
    assert not ns.sync_alert_due([d(1), d(4), d(10)], now)


# --- every athlete with a token, past the 1000-row page -------------------------------------

def test_run_tick_pages_push_tokens_and_chunks_athletes():
    ids = [f"a{i:04d}" for i in range(1500)]
    db = _Db(
        push_tokens=[{"athlete_id": i} for i in ids] + [{"athlete_id": "a0001"}],
        athletes=[{"id": i, "timezone_offset_min": 0, "notification_settings": None} for i in ids],
    )
    seen = []
    with patch.object(ns.cn, "admin_db", return_value=db), patch.object(ns, "tick_athlete", side_effect=lambda _db, a, _n: seen.append(a["id"])):
        ns.run_tick(datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
    assert sorted(seen) == ids
    athlete_chunks = [c for t, c in db.in_calls if t == "athletes"]
    assert len(athlete_chunks) == 8 and all(len(c) <= ns.ID_CHUNK for c in athlete_chunks)
