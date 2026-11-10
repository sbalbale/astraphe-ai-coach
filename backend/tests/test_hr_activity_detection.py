from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_current_athlete, get_user_db
from app.main import app
from app.routers import workouts as workouts_router
from app.services import hr_activity_detection as det
from app.services.heart_rate_series import (
    HeartRateSeries,
    parse_garmin_heart_rate_values,
    save_series,
    series_from_row,
)

T0 = datetime(2026, 11, 8, 5, 0, tzinfo=timezone.utc)
STEP = 120
REST, MAX = 55, 185  # reserve 130: enter >= 107 bpm, stay >= 94 bpm


def _day(blocks: list[tuple[int, int]], start: datetime = T0) -> list[tuple[datetime, int]]:
    """[(minutes, bpm), ...] -> a 2-minute grid series."""
    out, t = [], start
    for minutes, bpm in blocks:
        for _ in range(minutes // 2):
            out.append((t, bpm))
            t += timedelta(seconds=STEP)
    return out


# ---- Garmin parsing / storage ------------------------------------------------


def test_parse_garmin_values_drops_off_wrist_and_sorts():
    ms = int(T0.timestamp() * 1000)
    hr = {"heartRateValues": [[ms + 240_000, 70], [ms, 60], [ms + 120_000, None], [ms + 360_000, 0], "bad", [None, 80]]}
    assert parse_garmin_heart_rate_values(hr) == [(T0, 60), (T0 + timedelta(minutes=4), 70)]
    assert parse_garmin_heart_rate_values(None) == []
    assert parse_garmin_heart_rate_values({"heartRateValues": None}) == []


def test_save_series_round_trips_and_skips_empty():
    db = MagicMock()
    samples = _day([(6, 60)])
    assert save_series(db, "a1", date(2026, 11, 8), "garmin", [], 50) == 0
    db.table.assert_not_called()

    assert save_series(db, "a1", date(2026, 11, 8), "garmin", samples, 50) == 3
    row = db.table.return_value.upsert.call_args.args[0]
    assert row["offsets_sec"] == [0, 120, 240] and row["bpm"] == [60, 60, 60]
    assert db.table.return_value.upsert.call_args.kwargs["on_conflict"] == "athlete_id,date,source"
    back = series_from_row(row)
    assert back.samples == samples and back.resting_hr == 50


# ---- detect_windows ----------------------------------------------------------


def test_steady_session_detected_with_two_minute_boundaries():
    s = _day([(60, 60), (40, 140), (60, 60)])
    [w] = det.detect_windows(s, REST, MAX)
    assert w.start == T0 + timedelta(minutes=60)
    assert w.end == T0 + timedelta(minutes=100)
    assert w.duration_sec == 40 * 60 and w.avg_hr == 140 and w.max_hr == 140


def test_warm_tail_after_a_workout_is_not_part_of_it():
    # Real shape: session, then ~an hour of everyday HR hovering just above the stay
    # threshold with one short bump. The session ends with its last hard sample.
    s = _day([(30, 60), (2, 100), (30, 140), (24, 98), (2, 85), (20, 99), (6, 115), (20, 70)])
    [w] = det.detect_windows(s, REST, MAX)
    assert w.start == T0 + timedelta(minutes=30)  # the 100-bpm warm-up sample is included
    assert w.end == T0 + timedelta(minutes=62)


def test_short_spike_and_easy_activity_ignored():
    # 6 min hard (stairs), then 60 min at 100 bpm (above stay, below enter: a walk-ish day)
    s = _day([(30, 60), (6, 150), (30, 60), (60, 100), (30, 60)])
    assert det.detect_windows(s, REST, MAX) == []


def test_interval_rests_do_not_split_a_session():
    s = _day([(20, 60), (10, 140), (4, 85), (10, 140), (4, 85), (10, 140), (20, 60)])
    [w] = det.detect_windows(s, REST, MAX)
    assert w.duration_sec == (10 + 4 + 10 + 4 + 10) * 60


def test_long_rest_splits_into_two_sessions():
    s = _day([(20, 60), (20, 140), (30, 65), (20, 150), (20, 60)])
    assert len(det.detect_windows(s, REST, MAX)) == 2


def test_hole_in_series_ends_a_session():
    first = _day([(20, 140)])
    second = _day([(20, 140)], start=first[-1][0] + timedelta(minutes=30))
    ws = det.detect_windows(first + second, REST, MAX)
    assert [w.duration_sec for w in ws] == [20 * 60, 20 * 60]


def test_missing_or_degenerate_anchors_detect_nothing():
    s = _day([(40, 140)])
    assert det.detect_windows(s, None, MAX) == []
    assert det.detect_windows(s, REST, None) == []
    assert det.detect_windows(s, 60, 80) == []
    assert det.detect_windows([], REST, MAX) == []


# ---- detect_and_save_for_day ------------------------------------------------


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op = db, name, "select"

    def __getattr__(self, _attr):  # filters: eq/lt/gt/gte/in_/order/limit...
        return lambda *a, **k: self

    def delete(self):
        self.op = "delete"
        return self

    def maybe_single(self):
        self.op = "single"
        return self

    def execute(self):
        self.db.calls.append((self.name, self.op))
        rows = self.db.rows.get(self.name, [])
        return SimpleNamespace(data=(rows[0] if rows else None) if self.op == "single" else rows)


class _Db:
    def __init__(self, **rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        return _Q(self, name)


def _run(db, samples):
    series = HeartRateSeries("a1", date(2026, 11, 8), "garmin", samples, resting_hr=REST)
    saved = AsyncMock(return_value="w")
    with patch.object(det, "load_series", return_value=series), patch(
        "app.services.processing.process_and_save_workout", saved
    ), patch("app.services.processing._refresh_daily_strain_for_day_sync") as strain:
        result = asyncio.run(det.detect_and_save_for_day(db, "a1", date(2026, 11, 8)))
    return result, saved, strain


ATHLETE = {"id": "a1", "max_hr": MAX, "resting_hr": REST}
SESSION = _day([(60, 60), (40, 140), (60, 60)])
SESSION_START = T0 + timedelta(minutes=60)


def test_saves_detection_as_lowest_priority_workout():
    db = _Db(athletes=[ATHLETE])
    result, saved, strain = _run(db, SESSION)
    assert result == {"saved": 1, "removed": 0}
    payload = saved.call_args.args[0]
    assert payload.source == "hr_detected" and payload.workout_type == "other"
    assert payload.external_id == f"a1:{int(SESSION_START.timestamp())}"
    assert payload.duration_seconds == 2400 and payload.average_hr == 140
    assert sum(getattr(payload, f"hr_zone_{z}_pct") or 0 for z in range(1, 6)) in (99, 100, 101)
    assert saved.call_args.kwargs == {"skip_tss_recalc": True, "skip_daily_strain_refresh": True}
    strain.assert_called_once()


def test_recorded_workout_suppresses_overlapping_detection():
    recorded = {
        "id": "r1", "source": "garmin", "started_at": (SESSION_START + timedelta(minutes=3)).isoformat(),
        "ended_at": (SESSION_START + timedelta(minutes=38)).isoformat(),
    }
    result, saved, _ = _run(_Db(athletes=[ATHLETE], workouts=[recorded]), SESSION)
    assert result == {"saved": 0, "removed": 0}
    saved.assert_not_called()


def test_dismissed_window_not_detected_again():
    dismissal = {
        "started_at": SESSION_START.isoformat(),
        "ended_at": (SESSION_START + timedelta(minutes=40)).isoformat(),
    }
    result, saved, _ = _run(_Db(athletes=[ATHLETE], hr_detection_dismissals=[dismissal]), SESSION)
    assert result["saved"] == 0
    saved.assert_not_called()


def test_stale_detection_in_the_day_is_removed():
    stale = {
        "id": "d-old", "source": "hr_detected", "external_id": "a1:1",
        "started_at": (T0 + timedelta(minutes=10)).isoformat(),
        "ended_at": (T0 + timedelta(minutes=30)).isoformat(),
    }
    db = _Db(athletes=[ATHLETE], workouts=[stale])
    result, _, _ = _run(db, SESSION)
    assert result == {"saved": 1, "removed": 1}
    assert ("workouts", "delete") in db.calls


def test_no_series_does_nothing():
    db = _Db()
    with patch.object(det, "load_series", return_value=None):
        assert asyncio.run(det.detect_and_save_for_day(db, "a1", date(2026, 11, 8))) == {"saved": 0, "removed": 0}
    assert db.calls == []


def test_estimates_max_hr_from_birthday_when_profile_has_none():
    athlete = {"id": "a1", "resting_hr": REST, "date_of_birth": "1996-01-01"}  # ~30 -> Tanaka ~187
    result, _, _ = _run(_Db(athletes=[athlete]), SESSION)
    assert result["saved"] == 1


# ---- recorded workouts replace detections ------------------------------------


def test_recorded_workout_deletes_overlapping_detections():
    from app.services.processing import _find_or_create_canonical_workout_sync

    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "new"}])
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = SimpleNamespace(data=[])
    db.table.return_value.select.return_value.eq.return_value.neq.return_value.gte.return_value.lte.return_value.execute.return_value = SimpleNamespace(data=[])
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])

    _find_or_create_canonical_workout_sync(db, "a1", "strava", "run", SESSION_START, 2400)
    delete = db.table.return_value.delete.return_value
    delete.eq.assert_called_with("athlete_id", "a1")
    delete.eq.return_value.eq.assert_called_with("source", "hr_detected")

    db.reset_mock()
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "new"}])
    _find_or_create_canonical_workout_sync(db, "a1", "hr_detected", "other", SESSION_START, 2400, external_id="a1:1")
    db.table.return_value.delete.assert_not_called()


# ---- router: delete dismisses, edit confirms ---------------------------------


class _RouterDb:
    def __init__(self, row):
        self.row, self.updates = row, []

    def table(self, _name):
        outer = self

        class Q:
            single = False

            def __getattr__(self, _a):
                return lambda *a, **k: self

            def update(self, data):
                outer.updates.append(data)
                return self

            def maybe_single(self):
                self.single = True
                return self

            def execute(self):
                return SimpleNamespace(data=outer.row if self.single else [outer.row])

        return Q()


def _client(db):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    app.dependency_overrides[get_user_db] = lambda: db


DETECTED_ROW = {
    "id": "w1", "source": "hr_detected", "athlete_id": "athlete-1", "sport": "other",
    "started_at": "2026-11-08T06:00:00+00:00", "ended_at": "2026-11-08T06:40:00+00:00", "duration_seconds": 2400,
}


def test_deleting_a_detection_dismisses_its_window():
    _client(_RouterDb(dict(DETECTED_ROW)))
    try:
        with patch.object(workouts_router, "dismiss_detection") as dismiss, patch.object(
            workouts_router, "recalculate_tss_history"
        ), patch.object(workouts_router, "_refresh_daily_strain_for_instant_sync"):
            with TestClient(app) as client:
                res = client.delete("/v1/workouts/w1")
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 200
    dismiss.assert_called_once()
    assert dismiss.call_args.args[2]["source"] == "hr_detected"


def test_editing_a_detection_makes_it_manual():
    db = _RouterDb(dict(DETECTED_ROW))
    _client(db)
    try:
        with patch.object(workouts_router, "recalculate_tss_history"), patch.object(
            workouts_router, "_refresh_daily_strain_for_instant_sync"
        ):
            with TestClient(app) as client:
                res = client.patch("/v1/workouts/w1", json={"sport": "run"})
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 200
    assert db.updates[0]["source"] == "manual" and db.updates[0]["primary_source"] == "manual"


# ---- GET /v1/biometrics/heart-rate payload ------------------------------------


def test_merge_sleep_spans_unions_sources_and_keeps_nap_flag():
    from app.services.heart_rate_series import merge_sleep_spans

    rows = [
        {"started_at": "2026-11-08T04:00:00+00:00", "ended_at": "2026-11-08T11:00:00+00:00", "is_nap": False},
        {"started_at": "2026-11-08T04:10:00+00:00", "ended_at": "2026-11-08T11:30:00+00:00", "is_nap": False},
        {"started_at": "2026-11-08T18:00:00Z", "ended_at": "2026-11-08T18:40:00Z", "is_nap": True},
        {"started_at": "2026-11-08T20:00:00Z", "ended_at": "2026-11-08T19:00:00Z", "is_nap": True},  # bad
    ]
    assert merge_sleep_spans(rows) == [
        {"started_at": "2026-11-08T04:00:00Z", "ended_at": "2026-11-08T11:30:00Z", "is_nap": False},
        {"started_at": "2026-11-08T18:00:00Z", "ended_at": "2026-11-08T18:40:00Z", "is_nap": True},
    ]


def test_build_heart_rate_day_payload():
    from app.services import heart_rate_series as hrs

    series = HeartRateSeries("a1", date(2026, 11, 8), "garmin", SESSION, resting_hr=50)
    db = _Db(
        workouts=[{"id": "w", "source": "hr_detected", "started_at": "2026-11-08T06:00:00+00:00", "ended_at": "2026-11-08T06:40:00+00:00"}],
        sleep_periods=[],
        biometrics=[{"date": "2026-11-07", "resting_hr": 52}, {"date": "2026-11-08", "resting_hr": None}],
    )
    with patch.object(hrs, "load_series", return_value=series), patch(
        "app.services.time_utils.fetch_athlete_timezone_offset_min", return_value=-300
    ):
        p = hrs.build_heart_rate_day(db, "a1", date(2026, 11, 8))
    assert p["day_start"] == "2026-11-08T05:00:00Z" and p["interval_sec"] == 120
    assert p["min_hr"] == 60 and p["max_hr"] == 140 and len(p["samples"]) == len(SESSION)
    assert p["samples"][0] == {"t": "2026-11-08T05:00:00Z", "bpm": 60}
    assert p["workouts"][0]["detected"] is True and p["workouts"][0]["started_at"] == "2026-11-08T06:00:00Z"
    assert p["resting_hr_history"] == [{"date": "2026-11-07", "resting_hr": 52}]


def test_build_heart_rate_day_without_series():
    from app.services import heart_rate_series as hrs

    with patch.object(hrs, "load_series", return_value=None), patch(
        "app.services.time_utils.fetch_athlete_timezone_offset_min", return_value=0
    ):
        p = hrs.build_heart_rate_day(_Db(), "a1", date(2026, 11, 8))
    assert p["samples"] == [] and p["source"] is None and p["avg_hr"] is None and p["workouts"] == []


def test_unchanged_detection_is_not_saved_again():
    # An hourly re-run with nothing new must not re-save (the caller would rebuild the
    # whole TSS history on any "changed" count).
    w0 = det.detect_windows(SESSION, REST, MAX)[0]
    stored = {
        "id": "d1", "source": "hr_detected", "external_id": det.external_id_for("a1", w0.start),
        "started_at": w0.start.isoformat(), "ended_at": w0.end.isoformat(),
        "avg_hr": w0.avg_hr, "max_hr": w0.max_hr,
    }
    result, saved, strain = _run(_Db(athletes=[ATHLETE], workouts=[stored]), SESSION)
    assert result == {"saved": 0, "removed": 0}
    saved.assert_not_called()
    strain.assert_not_called()


def test_failed_dismissal_still_deletes_cleanly():
    _client(_RouterDb(dict(DETECTED_ROW)))
    try:
        with patch.object(workouts_router, "dismiss_detection", side_effect=RuntimeError("db")), patch.object(
            workouts_router, "recalculate_tss_history"
        ) as recalc, patch.object(workouts_router, "_refresh_daily_strain_for_instant_sync"):
            with TestClient(app) as client:
                res = client.delete("/v1/workouts/w1")
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 200
    recalc.assert_called_once()
