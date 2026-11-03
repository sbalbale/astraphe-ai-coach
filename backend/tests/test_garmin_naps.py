from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import garmin as garmin_service


def test_parse_naps_from_sleep_payload_iso_strings():
    sleep = {
        "dailySleepDTO": {"napTimeSeconds": 2280},
        "dailyNapDTOS": [
            {
                "napTimeSec": 2280,
                "napStartTimestampGMT": "2026-10-20T18:44:00.0",
                "napEndTimestampGMT": "2026-10-20T19:22:00.0",
                "calendarDate": "2026-10-20",
            }
        ],
    }
    [nap] = garmin_service.parse_garmin_naps(sleep)
    assert nap["start"] == datetime(2026, 10, 20, 18, 44, tzinfo=timezone.utc)
    assert nap["end"] == datetime(2026, 10, 20, 19, 22, tzinfo=timezone.utc)
    assert nap["duration_min"] == 38
    assert nap["calendar_date"] == "2026-10-20"


def test_parse_naps_from_list_epoch_ms_and_skips_bad_entries():
    start_ms = int(datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc).timestamp() * 1000)
    naps = garmin_service.parse_garmin_naps(
        [
            {"napStartTimestampGMT": start_ms, "napEndTimestampGMT": start_ms + 30 * 60_000},
            {"napStartTimestampGMT": start_ms, "napEndTimestampGMT": start_ms},  # zero length
            {"napStartTimestampGMT": None},
            "junk",
        ]
    )
    assert len(naps) == 1
    assert naps[0]["duration_min"] == 30  # falls back to the window when no nap time is given


def test_parse_naps_handles_missing_payload():
    assert garmin_service.parse_garmin_naps(None) == []
    assert garmin_service.parse_garmin_naps({"dailySleepDTO": {}}) == []


def test_save_naps_writes_nap_rows_dated_by_calendar_or_local_wake_day():
    db = MagicMock()
    naps = [
        {"start": datetime(2026, 10, 20, 18, 44, tzinfo=timezone.utc),
         "end": datetime(2026, 10, 20, 19, 22, tzinfo=timezone.utc),
         "duration_min": 36, "calendar_date": "2026-10-20"},
        # 23:30 UTC = 19:30 EDT the same day; no calendarDate, so local wake day applies.
        {"start": datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc),
         "end": datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc),
         "duration_min": 30, "calendar_date": None},
    ]
    dates = garmin_service.save_garmin_naps("ath-1", db, naps, timezone_offset_min=-240)
    rows = db.table.return_value.upsert.call_args.args[0]
    assert dates == ["2026-10-20", "2026-10-21"]
    assert all(r["is_nap"] and r["source"] == "garmin" for r in rows)
    assert rows[0]["in_bed_min"] == 38 and rows[0]["duration_min"] == 36 and rows[0]["awake_pct"] == 5.3
    assert rows[0]["external_id"].startswith("garmin:nap:ath-1:")
    assert db.table.return_value.upsert.call_args.kwargs["on_conflict"] == "athlete_id,source,external_id"


def test_fetch_day_saves_naps_before_the_summary():
    client = MagicMock()
    client.get_sleep_data.return_value = {
        "dailySleepDTO": {"sleepTimeSeconds": 28800, "napTimeSeconds": 1800},
        "dailyNapDTOS": [{"napStartTimestampGMT": "2026-10-20T18:00:00.0",
                          "napEndTimestampGMT": "2026-10-20T18:30:00.0", "calendarDate": "2026-10-20"}],
    }
    client.get_hrv_data.return_value = None
    client.get_heart_rates.return_value = None
    db = MagicMock()
    order: list[str] = []
    with patch.object(garmin_service, "save_garmin_naps", side_effect=lambda *a, **k: order.append("naps")), \
         patch.object(garmin_service, "process_and_save_biometrics", side_effect=lambda *a, **k: order.append("summary")):
        asyncio.run(garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, date(2026, 10, 20)))
    assert order == ["naps", "summary"]
    client.get_naps.assert_not_called()


def test_fetch_day_falls_back_to_get_naps_when_only_nap_time_is_reported():
    client = MagicMock()
    client.get_sleep_data.return_value = {"dailySleepDTO": {"sleepTimeSeconds": 28800, "napTimeSeconds": 1800}}
    client.get_hrv_data.return_value = None
    client.get_heart_rates.return_value = None
    client.get_naps.return_value = [{"napStartTimestampGMT": "2026-10-20T18:00:00.0",
                                     "napEndTimestampGMT": "2026-10-20T18:30:00.0"}]
    db = MagicMock()
    with patch.object(garmin_service, "save_garmin_naps") as save_naps, \
         patch.object(garmin_service, "process_and_save_biometrics"):
        asyncio.run(garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, date(2026, 10, 20)))
    client.get_naps.assert_called_once_with("2026-10-20")
    assert len(save_naps.call_args.args[2]) == 1
