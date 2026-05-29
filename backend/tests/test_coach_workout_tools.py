"""Tests for coach workout read/write tools."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from app.services import coach_tools, coach_workout_data


class WorkoutMockDB:
    """Supabase-like mock for workout coach tools."""

    def __init__(self):
        self.workouts: list[dict[str, Any]] = []
        self.plans: list[dict[str, Any]] = []
        self.laps: list[dict[str, Any]] = []
        self.streams: dict[str, dict[str, Any]] = {}
        self.athlete_row: dict[str, Any] = {
            "ftp_watts": 250,
            "lthr": 165,
            "threshold_hr": 165,
            "max_hr": 190,
            "resting_hr": 50,
            "hr_zone_method": "lthr",
            "threshold_pace": "5:00",
            "timezone_offset_min": 0,
        }

    def table(self, name: str) -> "_WTable":
        return _WTable(self, name)


class _WTable:
    def __init__(self, db: WorkoutMockDB, name: str):
        self._db = db
        self._name = name
        self._filters: list[tuple[str, Any]] = []
        self._gte: list[tuple[str, Any]] = []
        self._lte: list[tuple[str, Any]] = []
        self._order_desc = False
        self._limit: int | None = None
        self._maybe_single = False
        self._update_payload: dict[str, Any] | None = None
        self._delete = False

    def select(self, cols: str) -> "_WTable":
        return self

    def eq(self, col: str, val: Any) -> "_WTable":
        self._filters.append((col, val))
        return self

    def gte(self, col: str, val: Any) -> "_WTable":
        self._gte.append((col, val))
        return self

    def lte(self, col: str, val: Any) -> "_WTable":
        self._lte.append((col, val))
        return self

    def order(self, col: str, desc: bool = False) -> "_WTable":
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "_WTable":
        self._limit = n
        return self

    def maybe_single(self) -> "_WTable":
        self._maybe_single = True
        return self

    def update(self, payload: dict[str, Any]) -> "_WTable":
        self._update_payload = payload
        return self

    def delete(self) -> "_WTable":
        self._delete = True
        return self

    def execute(self) -> "_Exec":
        if self._name == "athletes":
            return _Exec(self._db.athlete_row if self._maybe_single else [self._db.athlete_row])

        if self._name == "workouts":
            if self._update_payload is not None:
                wid = next(v for k, v in self._filters if k == "id")
                for w in self._db.workouts:
                    if w["id"] == wid:
                        w.update(self._update_payload)
                        return _Exec([w])
                return _Exec([])

            rows = self._filter_workouts()
            if self._maybe_single:
                return _Exec(rows[0] if rows else None)
            return _Exec(rows)

        if self._name == "training_plans":
            if self._delete:
                pid = next(v for k, v in self._filters if k == "id")
                before = len(self._db.plans)
                self._db.plans = [p for p in self._db.plans if p["id"] != pid]
                return _Exec([{"id": pid}] if len(self._db.plans) < before else [])

            if self._update_payload is not None:
                pid = next(v for k, v in self._filters if k == "id")
                for p in self._db.plans:
                    if p["id"] == pid:
                        p.update(self._update_payload)
                        return _Exec([p])
                return _Exec([])

            rows = list(self._db.plans)
            for col, val in self._filters:
                rows = [r for r in rows if r.get(col) == val]
            for col, val in self._gte:
                rows = [r for r in rows if r.get(col) >= val]
            for col, val in self._lte:
                rows = [r for r in rows if r.get(col) <= val]
            if self._maybe_single:
                return _Exec(rows[0] if rows else None)
            return _Exec(rows)

        if self._name == "activity_laps":
            wid = next((v for k, v in self._filters if k == "workout_id"), None)
            rows = [l for l in self._db.laps if l.get("workout_id") == wid]
            return _Exec(rows)

        return _Exec([])

    def _filter_workouts(self) -> list[dict[str, Any]]:
        rows = list(self._db.workouts)
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        for col, val in self._gte:
            rows = [r for r in rows if r.get(col) >= val]
        for col, val in self._lte:
            rows = [r for r in rows if r.get(col) <= val]
        if self._order_desc:
            rows.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows


class _Exec:
    def __init__(self, data: Any):
        self.data = data


def _sample_workout(
    *,
    wid: str = "w1",
    sport: str = "bike",
    started_at: str | None = None,
    duration_seconds: int = 3600,
    tss: float = 80.0,
) -> dict[str, Any]:
    start = started_at or datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc).isoformat()
    end_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(seconds=duration_seconds)
    return {
        "id": wid,
        "athlete_id": "ath-1",
        "source": "strava",
        "primary_source": "strava",
        "sport": sport,
        "title": "Morning ride",
        "started_at": start,
        "ended_at": end_dt.isoformat(),
        "duration_seconds": duration_seconds,
        "distance_m": 40000,
        "avg_hr": 145,
        "max_hr": 172,
        "avg_power_w": 180,
        "norm_power_w": 195,
        "tss": tss,
        "strain_score": 55,
        "hr_zone_1_pct": 20,
        "hr_zone_2_pct": 50,
        "hr_zone_3_pct": 25,
        "hr_zone_4_pct": 5,
        "hr_zone_5_pct": 0,
        "strava_streams_fetched": True,
    }


def test_list_workouts_on_date():
    db = WorkoutMockDB()
    today = date.today()
    start = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc).isoformat()
    db.workouts.append(_sample_workout(started_at=start))

    out = coach_tools.handle_list_workouts(
        {"on_date": today.isoformat(), "sport": "bike"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["count"] == 1
    assert out["workouts"][0]["sport"] == "bike"


def test_get_workout_summary_by_id():
    db = WorkoutMockDB()
    db.workouts.append(_sample_workout())
    db.laps = [{"workout_id": "w1", "athlete_id": "ath-1", "id": "l1"}]

    out = coach_tools.handle_get_workout_summary(
        {"workout_id": "w1"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["id"] == "w1"
    assert out["duration_min"] == 60.0
    assert out["lap_count"] == 1


@patch("app.services.coach_workout_data.fetch_stream_row_columns")
def test_get_workout_streams_window_downsamples(mock_fetch):
    mock_fetch.return_value = {
        "time_series": {"heartrate": [120 + (i % 20) for i in range(900)]},
        "resolution_seconds": 1,
    }
    db = WorkoutMockDB()
    db.workouts.append(_sample_workout())

    out = coach_tools.handle_get_workout_streams_window(
        {"workout_id": "w1", "start_offset_min": 8, "end_offset_min": 12, "metrics": ["hr"]},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    assert out["metrics"]["hr"]["avg"] > 0
    assert len(out["metrics"]["hr"]["points"]) <= coach_workout_data.STREAM_TARGET_POINTS


@patch("app.services.coach_workout_data.fetch_stream_row_columns", return_value=None)
def test_get_workout_streams_unavailable(mock_fetch):
    db = WorkoutMockDB()
    db.workouts.append(_sample_workout())

    out = coach_tools.handle_get_workout_streams_window(
        {"workout_id": "w1", "start_offset_min": 0, "end_offset_min": 5},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["error"] == "streams_unavailable"


def test_get_athlete_zones_shape():
    db = WorkoutMockDB()
    out = coach_tools.handle_get_athlete_zones({}, athlete_id="ath-1", db=db)  # type: ignore[arg-type]
    assert "zones" in out
    assert len(out["zones"]) >= 5
    assert out["ftp_watts"] == 250


def test_log_workout_validation():
    db = WorkoutMockDB()
    out = coach_tools.handle_log_workout(
        {"sport": "row"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" in out


def test_log_workout_success():
    db = WorkoutMockDB()

    async def _fake_save(db_arg, athlete_id, payload):
        db_arg.workouts.append(
            {
                "id": "new-w1",
                "athlete_id": athlete_id,
                "sport": "row",
                "started_at": payload.start_time.isoformat(),
                "ended_at": payload.ended_at.isoformat() if payload.ended_at else None,
                "duration_seconds": payload.duration_seconds,
                "avg_power_w": payload.average_power,
                "tss": 42.5,
                "primary_source": "manual",
            }
        )
        return "new-w1", True

    with patch("app.services.coach_workout_data.asyncio.run") as run_mock, patch(
        "app.services.coach_workout_data.save_logged_workout", side_effect=_fake_save
    ):
        run_mock.side_effect = lambda coro: asyncio.get_event_loop().run_until_complete(coro)
        out = coach_tools.handle_log_workout(
            {"sport": "row", "duration_minutes": 60, "avg_power_w": 190, "on_date": "2026-05-29"},
            athlete_id="ath-1",
            db=db,  # type: ignore[arg-type]
        )
    assert out.get("status") == "created"
    assert out.get("workout_id") == "new-w1"


def test_update_workout_duration():
    db = WorkoutMockDB()
    db.workouts.append(_sample_workout())

    with patch("app.services.coach_workout_data.recalculate_tss_history"), patch(
        "app.services.coach_workout_data._refresh_daily_strain_for_day_sync"
    ):
        out = coach_tools.handle_update_workout(
            {"workout_id": "w1", "duration_minutes": 55},
            athlete_id="ath-1",
            db=db,  # type: ignore[arg-type]
        )
    assert out["status"] == "updated"
    assert db.workouts[0]["duration_seconds"] == 55 * 60


@patch("app.services.coach_workout_data.process_and_save_biometrics")
def test_log_biometrics(mock_save):
    db = WorkoutMockDB()
    out = coach_tools.handle_log_biometrics(
        {"on_date": "2026-05-29", "sleep_duration_min": 420, "resting_hr": 48},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["status"] == "saved"
    mock_save.assert_called_once()


def test_update_planned_workout():
    db = WorkoutMockDB()
    db.plans.append(
        {
            "id": "p1",
            "athlete_id": "ath-1",
            "planned_date": "2026-05-30",
            "sport": "bike",
            "title": "Endurance",
            "duration_min": 90,
        }
    )
    out = coach_tools.handle_update_planned_workout(
        {"plan_id": "p1", "new_date": "2026-05-31", "duration_minutes": 75},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["status"] == "updated"
    assert db.plans[0]["planned_date"] == "2026-05-31"
    assert db.plans[0]["duration_min"] == 75


def test_delete_planned_workout():
    db = WorkoutMockDB()
    db.plans.append(
        {"id": "p1", "athlete_id": "ath-1", "planned_date": "2026-05-30", "sport": "bike"}
    )
    out = coach_tools.handle_delete_planned_workout(
        {"plan_id": "p1"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["status"] == "deleted"
    assert len(db.plans) == 0


def test_build_log_workout_payload_bike_norm_from_avg():
    db = WorkoutMockDB()
    payload = coach_workout_data.build_log_workout_payload(
        db,  # type: ignore[arg-type]
        "ath-1",
        {"sport": "bike", "duration_minutes": 60, "avg_power_w": 200, "on_date": "2026-05-29"},
    )
    assert payload.normalized_power == 200
    assert payload.ftp_at_time == 250


def test_all_workout_tool_handlers_registered():
    expected = {
        "list_workouts",
        "get_workout_summary",
        "get_workout_streams_window",
        "log_workout",
        "update_workout",
        "log_biometrics",
        "get_athlete_zones",
        "update_planned_workout",
        "delete_planned_workout",
    }
    assert expected.issubset(set(coach_tools.TOOL_HANDLERS.keys()))
