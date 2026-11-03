"""After calendar changes the model gets what is actually saved, by weekday and by date."""
from unittest.mock import MagicMock

from app.services import ai_coach


def _db(rows):
    db = MagicMock()
    q = db.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value
    q.execute.return_value.data = rows
    return db


ROWS = [
    {"planned_date": "2026-11-02", "title": "Cat 1 Cross-Train Cycling", "sport": "bike", "duration_min": 90},
    {"planned_date": "2026-11-02", "title": "Team ST (Ferris)", "sport": "strength", "duration_min": 60},
    {"planned_date": "2026-11-03", "title": "Team ST (Rink)", "sport": "strength", "duration_min": 60},
    {"planned_date": "2026-11-04", "title": "Cat 1 Cross-Train Cycling", "sport": "bike", "duration_min": 90},
    {"planned_date": "2026-11-09", "title": "Team ST (Ferris)", "sport": "strength", "duration_min": 60},
]


def test_note_lists_the_weekday_pattern_and_dates():
    note = ai_coach._calendar_now_note(_db(ROWS), "a", ["2026-11-02", "2026-11-09"])
    assert "Monday: Team ST (Ferris) x2; Cat 1 Cross-Train Cycling x1" in note
    assert "Wednesday: Cat 1 Cross-Train Cycling x1" in note
    assert "Friday: nothing" in note
    assert "Tue 2026-11-03: Team ST (Rink) (strength, 60 min)" in note
    assert "describe only this" in note


def test_dates_touched_reads_args_and_results():
    got = ai_coach._dates_touched({"workouts": [{"date": "2026-11-02"}, {"date": "2026-11-05"}]}, {"scheduled": []})
    assert got == ["2026-11-02", "2026-11-05"]
    assert ai_coach._dates_touched({"start_date": "2026-11-01", "end_date": "2026-11-30"}, None) == ["2026-11-01", "2026-11-30"]
    assert ai_coach._dates_touched({"id": "x"}, {"planned_date": "2026-11-06"}) == ["2026-11-06"]


def test_no_dates_no_note():
    assert ai_coach._calendar_now_note(_db(ROWS), "a", []) is None
