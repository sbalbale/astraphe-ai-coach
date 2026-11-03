from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.routers import analysis
from app.services import garmin


def test_parse_day_defaults_to_athlete_local_today():
    with patch("app.services.time_utils.athlete_local_date", return_value=date(2026, 11, 4)):
        assert analysis._parse_day(None, object(), "a1") == date(2026, 11, 4)


def test_parse_day_explicit_day_wins():
    assert analysis._parse_day("2026-11-01", object(), "a1") == date(2026, 11, 1)


def test_garmin_sync_end_date_covers_east_of_utc_today():
    with patch.object(garmin, "_athlete_offset_min", return_value=14 * 60):
        end = garmin._sync_end_date(object(), "a1")
    assert end == (datetime.now(timezone.utc) + timedelta(hours=14)).date()


def test_garmin_sync_end_date_never_before_utc_today():
    with patch.object(garmin, "_athlete_offset_min", return_value=-12 * 60):
        end = garmin._sync_end_date(object(), "a1")
    assert end == datetime.now(timezone.utc).date()


def test_wake_epoch_date_fallback_is_utc_based():
    epoch = analysis._row_wake_epoch_s({"date": "2026-11-03"}, timezone_offset_min=60)
    assert epoch == datetime(2026, 11, 3, tzinfo=timezone.utc).timestamp() - 3600
