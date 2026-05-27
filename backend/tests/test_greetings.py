from datetime import datetime

from app.routers.analysis import _sanitize_analysis_content
from app.services.ai_coach import (
    _strip_leading_time_of_day_greeting,
    _time_of_day_greeting,
)


def test_time_of_day_greeting_uses_local_hour():
    assert _time_of_day_greeting(datetime(2026, 5, 26, 8, 0)) == "Good morning"
    assert _time_of_day_greeting(datetime(2026, 5, 26, 15, 0)) == "Good afternoon"
    assert _time_of_day_greeting(datetime(2026, 5, 26, 21, 0)) == "Good evening"


def test_coach_startup_strips_stale_leading_salutation():
    assert (
        _strip_leading_time_of_day_greeting("Good morning, your TSB is steady.")
        == "Your TSB is steady."
    )


def test_dashboard_summary_sanitizer_removes_time_of_day_salutation():
    text = _sanitize_analysis_content(
        "dashboard_summary",
        {},
        "Good morning, recovery is 82/100 and TSB is +6.",
    )

    assert text == "Recovery is 82/100 and TSB is +6."
