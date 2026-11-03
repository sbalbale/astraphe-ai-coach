"""The plan must survive chat edits (prod, 3 Nov 2026: each request cleared two months and
rescheduled only part of it, or nothing)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import ai_coach, coach_tools
from tests.test_ai_coach_agentic import _db_patches, _fc_part, _response, _text_part


def _run(message, script, db=None):
    """Drive the agent loop with scripted model responses; returns (reply, handler calls, db)."""
    db = db or MagicMock()
    calls = []
    steps = iter(script)

    def gen(*, model, contents, config):
        return next(steps)

    handlers = {
        "clear_training_plans": lambda a, i, d: calls.append(("clear", a)) or {"status": "success", "deleted": 40},
        "schedule_workouts": lambda a, i, d: calls.append(("schedule", a)) or {"scheduled_count": len(a["workouts"]), "scheduled": [], "failed": []},
    }
    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=gen), patch.dict(
        coach_tools.TOOL_HANDLERS, handlers
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", message, db=db)
    return text, calls, db


CLEAR_TWO_MONTHS = _fc_part("clear_training_plans", {"start_date": "2026-11-01", "end_date": "2026-12-31"})


def test_an_edit_never_runs_the_clear_and_only_replaces_rescheduled_days():
    script = [
        _response([CLEAR_TWO_MONTHS]),
        _response([_fc_part("schedule_workouts", {"workouts": [{"date": "2026-11-02"}, {"date": "2026-11-04"}]})]),
        _response([_text_part("<response>Added strength on Mon and Wed.</response>")]),
    ]
    text, calls, db = _run("add my team strength sessions on monday and wednesday", script)
    assert [c[0] for c in calls] == ["schedule"], "the two-month clear must not run"
    # Only the two rescheduled days were cleared, and only sessions not yet done.
    deletes = [c for c in db.mock_calls if ".delete()" in str(c)]
    assert deletes, "the rescheduled days are replaced"
    in_calls = [c for c in db.mock_calls if c[0].endswith(".in_")]
    assert any(c.args == ("planned_date", ["2026-11-02", "2026-11-04"]) for c in in_calls)
    assert text == "Added strength on Mon and Wed."


def test_a_clear_with_nothing_scheduled_deletes_nothing():
    script = [_response([CLEAR_TWO_MONTHS]), _response([_text_part("<response>Done.</response>")])]
    _, calls, db = _run("make thursdays a bit easier", script)
    assert calls == []
    assert not [c for c in db.mock_calls if ".delete()" in str(c)]


def test_an_explicit_request_still_clears():
    script = [_response([CLEAR_TWO_MONTHS]), _response([_text_part("<response>Cleared November and December.</response>")])]
    _, calls, _ = _run("clear my plan for november and december", script)
    assert [c[0] for c in calls] == ["clear"]


def test_claiming_a_filled_calendar_after_only_a_clear_is_pushed_back():
    script = [
        _response([CLEAR_TWO_MONTHS]),
        _response([_text_part("<response>The full two months are now live on your training calendar.</response>")]),
        _response([_fc_part("schedule_workouts", {"workouts": [{"date": "2026-11-03"}]})]),
        _response([_text_part("<response>Scheduled 1 session.</response>")]),
    ]
    text, calls, _ = _run("put the full two months into the plan", script)
    assert [c[0] for c in calls] == ["schedule"]
    assert text == "Scheduled 1 session."


def test_claim_detector_catches_the_prod_wording():
    for t in (
        "I have reviewed your schedule and integrated your preferences into the app.",
        "The full two months are now live on your training calendar.",
        "I have now pushed the full November training plan directly to your app calendar.",
        "Everything is fully populated and ready for your sessions today.",
    ):
        assert ai_coach._claims_plan_change(t), t
    assert not ai_coach._claims_plan_change("Want me to add strength on Mondays?")
