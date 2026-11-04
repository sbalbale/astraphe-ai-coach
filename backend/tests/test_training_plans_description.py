"""Plan rows: the app gets the coach's notes, never the workout JSON older rows stored."""
from app.routers.training_plans import _plain_description


def test_workout_json_is_not_shown_as_notes():
    raw = '{"sport": "strength", "focus_zone": "Recovery", "duration_minutes": 60, "structure": []}'
    assert _plain_description(raw) == ""


def test_notes_and_tables_are_kept():
    assert _plain_description("Smooth.\n\n| A | B |") == "Smooth.\n\n| A | B |"
    assert _plain_description("{not json} easy spin") == "{not json} easy spin"
    assert _plain_description(None) == ""
