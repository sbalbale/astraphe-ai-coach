"""Off-by-one dates are rejected; a nudge forces a tool call; every exit is claim-checked."""
from __future__ import annotations

from unittest.mock import patch

from app.services import ai_coach, coach_tools
from tests.test_ai_coach_agentic import _db_patches, _fc_part, _response, _text_part
from tests.test_coach_tools import MockCoachDB


def test_wrong_weekday_is_rejected_and_explained():
    out = coach_tools.handle_schedule_workout(
        {"date": "2026-11-03", "weekday": "Monday", "duration_minutes": 60, "focus_zone": "Endurance", "sport": "bike"},
        athlete_id="a",
        db=MockCoachDB(),  # type: ignore[arg-type]
    )
    assert out["error"].startswith("2026-11-03 is a Tuesday, not a Monday")


def test_right_weekday_is_accepted():
    db = MockCoachDB()
    out = coach_tools.handle_schedule_workout(
        {"date": "2026-11-03", "weekday": "tue", "duration_minutes": 60, "focus_zone": "Endurance", "sport": "bike"},
        athlete_id="a",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out


def test_batch_items_require_a_weekday():
    assert "weekday" in coach_tools._schedule_many_item.required


def test_after_a_nudge_the_next_call_must_use_a_tool():
    seen = []
    script = iter([
        _response([_text_part("<response>I have scheduled everything through December.</response>")]),
        _response([_fc_part("schedule_workouts", {"workouts": [{"date": "2026-12-01", "weekday": "Tuesday"}]})]),
        _response([_text_part("<response>Scheduled 1 session.</response>")]),
    ])

    def gen(*, model, contents, config):
        fc = getattr(getattr(config, "tool_config", None), "function_calling_config", None)
        seen.append(getattr(fc, "mode", None))
        return next(script)

    with _db_patches(), patch.object(ai_coach._client.models, "generate_content", side_effect=gen), patch.dict(
        coach_tools.TOOL_HANDLERS, {"schedule_workouts": lambda a, i, d: {"scheduled_count": 1, "scheduled": [], "failed": []}}
    ):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "fill out the calendar through december", db=object())
    assert str(seen[1]).endswith("ANY"), seen  # forced on the hop after the nudge
    assert seen[2] in (None,) or not str(seen[2]).endswith("ANY")  # back to normal after
    assert text == "Scheduled 1 session."


def test_fallback_reply_is_claim_checked_too():
    # The model never produces a usable answer; the wrap-up text claims a change.
    with _db_patches(), patch.object(
        ai_coach._client.models, "generate_content", return_value=_response([])
    ), patch.object(ai_coach, "_wrap_up_after_tool_budget", return_value="I have updated your whole plan."):
        text, _ = ai_coach.get_coach_response_agentic("ath-1", "fill out december", db=object())
    assert "nothing was actually saved" in text
