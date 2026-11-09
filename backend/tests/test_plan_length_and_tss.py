"""A planned session's length, blocks and TSS always agree, and TSS is computed by us.

Prod: the coach set Wednesday's Cat 1 ride to 90' but only duration_min changed; its one 60'
block stayed, so the app kept showing 60' (and the coach, reading back 90, said it had worked).
The plan API then scaled the block-based TSS by 60/90, so the same 60' ride showed 33 on
Wednesday and 49 on Friday.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.routers.training_plans import _to_workout_row
from app.services import coach_workout_data as cwd
from app.services.coach_tools import consistent_plan_fields, resize_structure

CAT1 = [{"name": "Steady state", "description": "Cat 1", "sub_intervals": [], "target_hr_zone": 2, "duration_minutes": 60}]


def _row(**over):
    row = {
        "id": "p1", "planned_date": "2026-11-11", "sport": "bike", "title": "Cat 1 bike",
        "duration_min": 60, "target_tss": 49, "primary_zone": "Endurance", "structure": CAT1, "status": "planned",
    }
    row.update(over)
    return row


def _update_db(row):
    """Fake that returns `row` for the lookup and records the update payload."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        SimpleNamespace(data=row)
    )
    saved = {}

    def _update(payload):
        saved.update(payload)
        chain = MagicMock()
        chain.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[{**row, **payload}])
        return chain

    db.table.return_value.update.side_effect = _update
    return db, saved


def test_resize_single_block():
    assert resize_structure(CAT1, 90)[0]["duration_minutes"] == 90
    assert CAT1[0]["duration_minutes"] == 60  # input untouched


def test_resize_puts_the_change_on_the_main_block():
    blocks = [
        {"name": "Warm-up", "duration_minutes": 10},
        {"name": "Main", "duration_minutes": 40},
        {"name": "Cool-down", "duration_minutes": 10},
    ]
    assert [b["duration_minutes"] for b in resize_structure(blocks, 90)] == [10, 70, 10]


def test_resize_refuses_interval_only_sessions():
    reps = [{"name": "5x4", "duration_minutes": 40, "sub_intervals": [{"duration_minutes": 4}]}]
    assert resize_structure(reps, 60) is None


def test_same_blocks_same_tss_whatever_duration_min_says():
    assert consistent_plan_fields(CAT1, 90, "Endurance") == consistent_plan_fields(CAT1, 60, "Endurance") == (60, 49)


def test_strength_without_blocks_counts_as_zone_1():
    # 60' at IF 0.55, as in the app's plan editor
    assert consistent_plan_fields([], 60, "Endurance", "strength") == (60, 30)


def test_coach_setting_90_minutes_retimes_the_block_and_tss():
    db, saved = _update_db(_row())
    result = cwd.update_planned_workout_sync(db, "a1", {"plan_id": "p1", "duration_minutes": 90})
    assert result["status"] == "updated"
    assert saved["duration_min"] == 90
    assert saved["structure"][0]["duration_minutes"] == 90
    assert saved["target_tss"] == consistent_plan_fields(saved["structure"], 90, "Endurance")[1] == 74


def test_coach_new_blocks_set_the_length():
    db, saved = _update_db(_row())
    blocks = [{"name": "Z2", "target_hr_zone": 2, "duration_minutes": 45}, {"name": "Z2", "target_hr_zone": 2, "duration_minutes": 45}]
    cwd.update_planned_workout_sync(db, "a1", {"plan_id": "p1", "duration_minutes": 60, "structure": blocks})
    assert saved["duration_min"] == 90


def test_coach_gets_an_error_it_can_act_on_for_interval_sessions():
    reps = [{"name": "5x4", "duration_minutes": 40, "sub_intervals": [{"duration_minutes": 4}]}]
    db, saved = _update_db(_row(structure=reps, duration_min=40))
    result = cwd.update_planned_workout_sync(db, "a1", {"plan_id": "p1", "duration_minutes": 60})
    assert result["error"] == "cannot_resize_blocks"
    assert not saved


def test_plan_api_shows_one_tss_for_the_same_blocks():
    wed = _to_workout_row(_row(duration_min=90))
    fri = _to_workout_row(_row(duration_min=60))
    assert (wed["duration_minutes"], wed["projected_tss"]) == (fri["duration_minutes"], fri["projected_tss"]) == (60, 49)


def test_session_picked_by_date_is_resized_too():
    """resolve_plan_row by date used a query without blocks, so there was nothing to resize."""
    from app.services.coach_workout_data import query_planned_workouts

    db = MagicMock()
    query_planned_workouts(db, "a1", __import__("datetime").date(2026, 11, 11), __import__("datetime").date(2026, 11, 11))
    assert "structure" in db.table.return_value.select.call_args.args[0]


def test_prescription_table_follows_new_blocks():
    """Prod: the coach stretched Wednesday to 90' but its Prescription still said 60 min."""
    notes = "Keep it conversational.\n\n| Phase | Duration | Intensity | Target |\n| :--- | :---: | :---: | :--- |\n| Steady State | 60 min | Z2 | Cat 1 |"
    db, saved = _update_db(_row(description=notes))
    cwd.update_planned_workout_sync(db, "a1", {"plan_id": "p1", "duration_minutes": 90})
    assert "| Steady state | 90 min | Z2 | Cat 1 |" in saved["description"]
    assert "60 min" not in saved["description"]
    assert saved["description"].startswith("Keep it conversational.")


def test_prescription_table_folds_interval_sets():
    from app.services.coach_tools import prescription_table

    blocks = [
        {"name": "Work 1/2", "duration_minutes": 4, "target_power_percent_ftp": 105, "description": "294 W"},
        {"name": "Recovery 1/1", "duration_minutes": 2, "target_hr_zone": 1},
        {"name": "Work 2/2", "duration_minutes": 4, "target_power_percent_ftp": 105, "description": "294 W"},
    ]
    assert "| Intervals | 2 x 4:00 min / 2:00 min easy | 105% FTP | 294 W |" in prescription_table(blocks)


def test_title_only_edit_leaves_notes_alone():
    db, saved = _update_db(_row(description="My notes"))
    cwd.update_planned_workout_sync(db, "a1", {"plan_id": "p1", "title": "Renamed"})
    assert "description" not in saved
