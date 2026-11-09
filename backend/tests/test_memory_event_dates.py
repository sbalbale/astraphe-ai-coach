"""Memories about events that are over don't read as goals (prod: chips still suggested
training for a 70.3 raced in July; its memories had no event_date, only the date in the text)."""

from datetime import date

from app.services.memory import memories_for_context, memory_event_date


def test_event_date_column_wins():
    assert memory_event_date({"event_date": "2026-07-26", "content": "Race on June 1"}) == date(2026, 7, 26)


def test_date_written_with_year():
    m = {"content": "Competing in the bike leg of IRONMAN 70.3 Maine in Augusta, ME on July 26, 2026."}
    assert memory_event_date(m) == date(2026, 7, 26)


def test_date_without_year_uses_the_year_it_was_saved():
    m = {"content": "Race: IRONMAN 70.3 Maine bike leg on July 26.", "created_at": "2026-06-30T12:00:00+00:00"}
    assert memory_event_date(m) == date(2026, 7, 26)


def test_date_without_year_earlier_than_saving_is_next_year():
    m = {"content": "Marathon on March 3rd", "created_at": "2026-11-01T00:00:00+00:00"}
    assert memory_event_date(m) == date(2027, 3, 3)


def test_no_date_and_bad_dates():
    assert memory_event_date({"content": "Prefers morning rides"}) is None
    assert memory_event_date({"content": "Race on Feb 30"}) is None


def test_coach_context_marks_text_dated_races_past():
    [entry] = memories_for_context(
        [{"content": "Race: IRONMAN 70.3 Maine on July 26.", "created_at": "2026-06-30T00:00:00+00:00"}],
        "2026-11-09",
    )
    assert entry["event_status"] == "past"
