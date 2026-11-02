from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import garmin as garmin_service

# Trimmed + anonymised from a real get_sleep_data() night: only the fields the parser
# reads, timestamps shifted to an arbitrary date, no ids. activityLevel: 0 deep,
# 1 light, 2 rem, 3 awake. Segments are contiguous (no gaps) in the real data.
SLEEP_LEVELS = [
    {"startGMT": "2026-05-20T03:09:18.0", "endGMT": "2026-05-20T03:24:18.0", "activityLevel": 1.0},
    {"startGMT": "2026-05-20T03:24:18.0", "endGMT": "2026-05-20T04:01:18.0", "activityLevel": 0.0},
    {"startGMT": "2026-05-20T04:01:18.0", "endGMT": "2026-05-20T04:14:18.0", "activityLevel": 1.0},
    {"startGMT": "2026-05-20T04:14:18.0", "endGMT": "2026-05-20T04:15:18.0", "activityLevel": 3.0},
    {"startGMT": "2026-05-20T04:15:18.0", "endGMT": "2026-05-20T04:22:18.0", "activityLevel": 1.0},
    {"startGMT": "2026-05-20T04:22:18.0", "endGMT": "2026-05-20T04:41:18.0", "activityLevel": 2.0},
    {"startGMT": "2026-05-20T04:41:18.0", "endGMT": "2026-05-20T05:26:18.0", "activityLevel": 1.0},
    {"startGMT": "2026-05-20T05:26:18.0", "endGMT": "2026-05-20T05:39:18.0", "activityLevel": 0.0},
    {"startGMT": "2026-05-20T05:39:18.0", "endGMT": "2026-05-20T06:13:18.0", "activityLevel": 1.0},
    {"startGMT": "2026-05-20T06:13:18.0", "endGMT": "2026-05-20T06:42:18.0", "activityLevel": 0.0},
]
SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 12720}, "sleepLevels": SLEEP_LEVELS}
DAY = date(2026, 5, 20)


# ---- parser ---------------------------------------------------------------


def test_parse_maps_codes_and_durations_match_totals():
    segs = garmin_service.parse_sleep_stage_segments(SLEEP)
    assert len(segs) == 10
    totals: dict[str, float] = {}
    for s in segs:
        totals[s["stage"]] = totals.get(s["stage"], 0) + (s["end_at"] - s["start_at"]).total_seconds()
    # same totals as the real night's dailySleepDTO deep/light/rem/awake seconds
    assert totals == {"deep": 4740, "light": 6840, "rem": 1140, "awake": 60}


def test_parse_timestamps_are_utc_aware_and_sorted():
    segs = garmin_service.parse_sleep_stage_segments({"sleepLevels": list(reversed(SLEEP_LEVELS))})
    assert segs[0]["start_at"] == datetime(2026, 5, 20, 3, 9, 18, tzinfo=timezone.utc)
    assert all(s["start_at"].tzinfo is not None for s in segs)
    assert [s["start_at"] for s in segs] == sorted(s["start_at"] for s in segs)


def test_parse_missing_or_empty_gives_no_segments():
    assert garmin_service.parse_sleep_stage_segments(None) == []
    assert garmin_service.parse_sleep_stage_segments({}) == []
    assert garmin_service.parse_sleep_stage_segments({"sleepLevels": None}) == []
    assert garmin_service.parse_sleep_stage_segments({"sleepLevels": []}) == []


def test_parse_skips_unknown_code_and_bad_segments_without_crashing():
    levels = SLEEP_LEVELS[:2] + [
        {"startGMT": "2026-05-20T06:42:18.0", "endGMT": "2026-05-20T06:50:18.0", "activityLevel": -1.0},
        {"startGMT": "2026-05-20T06:50:18.0", "endGMT": "2026-05-20T06:55:18.0", "activityLevel": None},
        {"startGMT": "garbage", "endGMT": "2026-05-20T06:55:18.0", "activityLevel": 1.0},
        {"startGMT": "2026-05-20T07:00:00.0", "endGMT": "2026-05-20T06:00:00.0", "activityLevel": 1.0},
        "not-a-dict",
    ]
    segs = garmin_service.parse_sleep_stage_segments({"sleepLevels": levels})
    assert [s["stage"] for s in segs] == ["light", "deep"]


# ---- persistence / idempotency -------------------------------------------


class _FakeSegmentsDb:
    """Minimal in-memory sleep_stage_segments honouring delete filters + upsert uniqueness."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}

    def table(self, name):
        assert name == "sleep_stage_segments"
        return _Table(self)


class _Table:
    def __init__(self, db):
        self.db = db
        self._filters: dict = {}
        self._op = None

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def upsert(self, rows, on_conflict=None):
        assert on_conflict == "athlete_id,source,start_at"
        for r in rows:
            self.db.rows[(r["athlete_id"], r["source"], r["start_at"])] = dict(r)
        return self

    def execute(self):
        if self._op == "delete":
            self.db.rows = {
                k: v for k, v in self.db.rows.items()
                if not all(v.get(c) == x for c, x in self._filters.items())
            }
        return MagicMock()


def test_save_is_idempotent_for_same_night():
    db = _FakeSegmentsDb()
    segs = garmin_service.parse_sleep_stage_segments(SLEEP)
    assert garmin_service.save_sleep_stage_segments("ath-1", db, DAY, segs) == 10
    first = sorted(db.rows.values(), key=lambda r: r["start_at"])
    assert garmin_service.save_sleep_stage_segments("ath-1", db, DAY, segs) == 10
    second = sorted(db.rows.values(), key=lambda r: r["start_at"])
    assert len(second) == 10
    assert second == first
    assert {r["source"] for r in second} == {"garmin"} and {r["date"] for r in second} == {"2026-05-20"}


def test_resync_replaces_stale_rows_for_that_night_only():
    db = _FakeSegmentsDb()
    other_night = garmin_service.parse_sleep_stage_segments(
        {"sleepLevels": [{"startGMT": "2026-05-19T03:00:00.0", "endGMT": "2026-05-19T04:00:00.0", "activityLevel": 0.0}]}
    )
    garmin_service.save_sleep_stage_segments("ath-1", db, date(2026, 5, 19), other_night)
    garmin_service.save_sleep_stage_segments("ath-1", db, DAY, garmin_service.parse_sleep_stage_segments(SLEEP))
    # Garmin revises the night: fewer segments now
    garmin_service.save_sleep_stage_segments("ath-1", db, DAY, garmin_service.parse_sleep_stage_segments(SLEEP)[:3])
    assert len([r for r in db.rows.values() if r["date"] == "2026-05-20"]) == 3
    assert len([r for r in db.rows.values() if r["date"] == "2026-05-19"]) == 1


def test_save_with_no_segments_touches_nothing():
    db = MagicMock()
    assert garmin_service.save_sleep_stage_segments("ath-1", db, DAY, []) == 0
    db.table.assert_not_called()


# ---- wiring in the per-day sync ------------------------------------------


def _client(sleep):
    c = MagicMock()
    c.get_sleep_data.return_value = sleep
    c.get_hrv_data.return_value = {"hrvSummary": {"lastNightAvg": 55}}
    c.get_heart_rates.return_value = {"restingHeartRate": 48}
    return c


def test_day_sync_twice_yields_same_rows_and_makes_no_extra_garmin_calls():
    db, client = _FakeSegmentsDb(), _client(SLEEP)
    with patch.object(garmin_service, "process_and_save_biometrics"):
        for _ in range(2):
            asyncio.run(garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, DAY))
    assert len(db.rows) == 10
    assert client.get_sleep_data.call_count == 2  # one per sync, nothing added for segments


def test_day_sync_stores_segments_even_if_summary_save_is_skipped():
    # payload may be None / another source may win the summary; segments are independent
    db = _FakeSegmentsDb()
    client = _client(SLEEP)
    client.get_hrv_data.return_value = None
    client.get_heart_rates.return_value = None
    with patch.object(garmin_service, "_daily_biometrics_from_garmin", return_value=None), \
         patch.object(garmin_service, "process_and_save_biometrics") as save:
        assert asyncio.run(garmin_service.fetch_and_store_biometrics_for_day("ath-1", db, client, DAY)) is False
    save.assert_not_called()
    assert len(db.rows) == 10


def test_day_sync_segment_failure_does_not_break_biometrics():
    client = _client(SLEEP)
    with patch.object(garmin_service, "save_sleep_stage_segments", side_effect=RuntimeError("db down")), \
         patch.object(garmin_service, "process_and_save_biometrics") as save:
        assert asyncio.run(garmin_service.fetch_and_store_biometrics_for_day("ath-1", MagicMock(), client, DAY)) is True
    save.assert_called_once()


def test_day_sync_without_sleep_levels_writes_no_rows():
    db = _FakeSegmentsDb()
    with patch.object(garmin_service, "process_and_save_biometrics"):
        asyncio.run(
            garmin_service.fetch_and_store_biometrics_for_day(
                "ath-1", db, _client({"dailySleepDTO": {"sleepTimeSeconds": 28800}}), DAY
            )
        )
    assert db.rows == {}
