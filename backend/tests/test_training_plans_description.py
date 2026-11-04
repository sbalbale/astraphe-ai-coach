"""Plan rows: the app gets the coach's notes, never the workout JSON older rows stored."""
from app.routers.training_plans import _plain_description


def test_workout_json_is_not_shown_as_notes():
    raw = '{"sport": "strength", "focus_zone": "Recovery", "duration_minutes": 60, "structure": []}'
    assert _plain_description(raw) == ""


def test_notes_and_tables_are_kept():
    assert _plain_description("Smooth.\n\n| A | B |") == "Smooth.\n\n| A | B |"
    assert _plain_description("{not json} easy spin") == "{not json} easy spin"
    assert _plain_description(None) == ""


def test_length_is_the_blocks_total():
    from app.routers.training_plans import _to_workout_row

    row = {"id": "p", "planned_date": "2026-11-04", "duration_min": 90, "target_tss": 74,
           "structure": [{"name": "Steady", "duration_minutes": 60, "target_hr_zone": 2}]}
    w = _to_workout_row(row)
    assert w["duration_minutes"] == 60 and w["projected_tss"] == 49
    row["structure"] = [{"name": "A", "duration_minutes": 35}, {"name": "B", "duration_minutes": 35}]
    assert _to_workout_row(row)["duration_minutes"] == 70
    row["structure"] = []
    assert _to_workout_row(row)["duration_minutes"] == 90  # no blocks: the stated length
