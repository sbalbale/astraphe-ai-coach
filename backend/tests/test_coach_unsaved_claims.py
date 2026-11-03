"""A reply that says the calendar was changed when no write tool ran (prod, 3 Nov 2026:
"I have scheduled your full two-month plan…", nothing saved, twice)."""
from __future__ import annotations

from unittest.mock import patch

from app.services import ai_coach, coach_tools
from tests.test_ai_coach_agentic import _db_patches, _fc_part, _response, _text_part

CLAIM = "<response>I have mapped out and scheduled your full two-month plan right into your calendar.</response>"


def test_claim_detector():
    assert ai_coach._claims_plan_change("I have just cleared your calendar and populated it")
    assert ai_coach._claims_plan_change("Everything is synced to your app.")
    assert ai_coach._claims_plan_change("Check your calendar now.")
    assert not ai_coach._claims_plan_change("You should schedule a rest day after the long ride.")
    assert not ai_coach._claims_plan_change("Want me to add a recovery spin on Sunday?")
    assert not ai_coach._claims_plan_change("HRV is up 10% and sleep was solid.")


def test_claim_without_tools_gets_one_nudge_then_the_tools_run():
    calls = {"n": 0}
    ran = []

    def gen(*, model, contents, config):
        calls["n"] += 1
        if calls["n"] == 1:
            return _response([_text_part(CLAIM)])
        if calls["n"] == 2:
            # After the nudge the model actually schedules.
            assert "NOTHING was saved" in contents[-1].parts[0].text
            return _response([_fc_part("schedule_workouts", {"workouts": [{"date": "2026-11-10"}]})])
        return _response([_text_part("<response>Scheduled 1 session on 10 Nov.</response>")])

    handler = lambda args, aid, db: ran.append(args) or {"scheduled_count": 1, "scheduled": [], "failed": []}
    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=gen), patch.dict(
        coach_tools.TOOL_HANDLERS, {"schedule_workouts": handler}
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "put the full two months into the plan", db=object())
    assert ran, "the schedule tool should have run after the nudge"
    assert text == "Scheduled 1 session on 10 Nov."


def test_claim_that_persists_is_flagged_as_not_saved():
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", return_value=_response([_text_part(CLAIM)])
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "put the plan in my calendar", db=object())
    assert text.startswith("I have mapped out")
    assert "nothing was actually saved" in text


def test_real_tool_call_is_not_second_guessed():
    calls = {"n": 0}

    def gen(*, model, contents, config):
        calls["n"] += 1
        if calls["n"] == 1:
            return _response([_fc_part("schedule_workout", {"date": "2026-11-10", "duration_minutes": 60, "focus_zone": "Endurance"})])
        return _response([_text_part("<response>I've scheduled an easy hour on 10 Nov.</response>")])

    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=gen), patch.dict(
        coach_tools.TOOL_HANDLERS, {"schedule_workout": lambda a, i, d: {"planned_date": "2026-11-10"}}
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "schedule an easy hour on the 10th", db=object())
    assert text == "I've scheduled an easy hour on 10 Nov."
    assert calls["n"] == 2
