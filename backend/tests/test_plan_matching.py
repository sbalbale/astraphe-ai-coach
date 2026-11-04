"""Matching recorded workouts to planned sessions: fit rules and suggestions."""
from __future__ import annotations

from app.services import plan_matching as pm

EST = -300  # UTC-5


def _plan(**kw):
    return {"id": "p1", "planned_date": "2026-11-03", "sport": "bike", "duration_min": 90, "target_tss": 105,
            "status": "planned", "completed_workout_id": None, "dismissed_workout_ids": [], **kw}


def _w(**kw):
    # 08:00 local on 3 Nov
    return {"id": "w1", "sport": "bike", "title": "Morning ride", "started_at": "2026-11-03T13:00:00+00:00",
            "duration_seconds": 88 * 60, "tss": 98, **kw}


def test_same_day_same_sport_similar_duration_auto_matches():
    f = pm.fit(_plan(), _w(), EST)
    assert f["auto_ok"] and f["day_offset"] == 0 and f["reason"] == "same day · similar duration"


def test_local_day_uses_the_athletes_offset():
    # 02:00 UTC on 4 Nov is still 3 Nov at 21:00 in UTC-5.
    assert pm.fit(_plan(), _w(started_at="2026-11-04T02:00:00Z"), EST)["day_offset"] == 0
    assert pm.fit(_plan(), _w(started_at="2026-11-04T02:00:00Z"), 0)["day_offset"] == 1


def test_auto_match_needs_sport_and_duration_within_50_to_150_percent():
    assert not pm.fit(_plan(), _w(sport="run"), EST)["auto_ok"]
    assert not pm.fit(_plan(), _w(duration_seconds=40 * 60), EST)["auto_ok"]  # 44%
    assert pm.fit(_plan(), _w(duration_seconds=130 * 60), EST)["auto_ok"]  # 144%
    assert not pm.fit(_plan(), _w(duration_seconds=140 * 60), EST)["auto_ok"]  # 156%
    assert not pm.fit(_plan(), _w(started_at="2026-11-04T13:00:00Z"), EST)["auto_ok"]  # a day late


def test_reasons_and_aliases():
    assert pm.fit(_plan(), _w(started_at="2026-11-04T13:00:00Z"), EST)["reason"].startswith("1 day late")
    assert pm.fit(_plan(), _w(sport="run"), EST)["reason"] == "different sport"
    assert pm.normalize_sport("Cycling") == "bike" and pm.normalize_sport("gym") == "strength"


def test_closer_duration_scores_better():
    a = pm.fit(_plan(), _w(duration_seconds=90 * 60), EST)["score"]
    b = pm.fit(_plan(), _w(duration_seconds=60 * 60), EST)["score"]
    assert a < b


def _row(**kw):
    base = {"fit": {"sport_ok": True}, "dismissed": False, "linked_to": None, "linked_here": False}
    base.update(kw)
    return base


def test_suggestion_skips_dismissed_linked_elsewhere_and_other_sports():
    rows = [
        _row(id="a", dismissed=True),
        _row(id="b", linked_to={"id": "p9"}),
        _row(id="c", fit={"sport_ok": False}),
        _row(id="d"),
    ]
    assert pm._suggestion(_plan(), rows)["id"] == "d"
    assert pm._suggestion(_plan(status="done"), rows) is None


# --- review fixes: races, undo, ids -------------------------------------------------------

def test_unlink_for_undo_does_not_dismiss():
    from unittest.mock import patch as _patch

    from app.services import plan_matching as pm

    updates = []
    plan = {"id": "p1", "completed_workout_id": "w1", "dismissed_workout_ids": []}
    with _patch.object(pm, "_plan", return_value=plan), _patch.object(
        pm, "_clear_link", side_effect=lambda db, a, pid, dismiss=None, prior=None, done=False: updates.append((dismiss, done)) or {"id": pid}
    ):
        pm.unlink(None, "a", "p1", dismiss=False, done=True)
        pm.unlink(None, "a", "p1")
    assert updates == [(None, True), ("w1", False)]


def test_auto_link_never_overwrites_a_completed_session():
    from unittest.mock import patch as _patch

    import pytest as _pytest

    from app.services import plan_matching as pm

    plan = {"id": "p1", "completed_workout_id": "w-other", "date": "2026-11-02", "title": "Ride"}
    with _patch.object(pm, "_plan", return_value=plan), _patch.object(pm, "_workout", return_value={"id": "w1"}):
        with _pytest.raises(pm.LinkConflict):
            pm.link(None, "a", "p1", "w1", source="auto")


def test_a_unique_violation_becomes_a_conflict_and_restores_a_moved_link():
    from unittest.mock import MagicMock, patch as _patch

    import pytest as _pytest

    from app.services import plan_matching as pm

    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint (23505)"
    )
    other = {"id": "p-other", "completed_workout_id": "w1", "status": "done", "link_source": "manual"}
    restored = []
    with _patch.object(pm, "_plan", return_value={"id": "p1", "dismissed_workout_ids": []}), _patch.object(
        pm, "_workout", return_value={"id": "w1"}
    ), _patch.object(pm, "_linked_plan_for_workout", side_effect=[other, other]), _patch.object(
        pm, "_clear_link", return_value={}
    ), _patch.object(pm, "_restore_link", side_effect=lambda db, a, prior: restored.append(prior["id"])), _patch.object(
        pm, "plan_summary", side_effect=lambda p: {"id": p["id"]}
    ):
        with _pytest.raises(pm.LinkConflict) as exc:
            pm.link(db, "a", "p1", "w1", move=True)
    assert restored == ["p-other"]
    assert exc.value.other == {"id": "p-other"}
