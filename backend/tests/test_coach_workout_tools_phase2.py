"""Phase 2/3 coach workout tools: plan reads, PMC series, biometrics, aggregates."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services import coach_tools, coach_workout_data


class Phase2MockDB:
    """Extended mock for phase 2/3 workout coach tools."""

    def __init__(self):
        self.workouts: list[dict[str, Any]] = []
        self.plans: list[dict[str, Any]] = []
        self.tss_history: list[dict[str, Any]] = []
        self.biometrics: list[dict[str, Any]] = []
        self.athlete_row: dict[str, Any] = {
            "ftp_watts": 250,
            "timezone_offset_min": 0,
        }

    def table(self, name: str) -> "_P2Table":
        return _P2Table(self, name)


class _P2Table:
    def __init__(self, db: Phase2MockDB, name: str):
        self._db = db
        self._name = name
        self._filters: list[tuple[str, Any]] = []
        self._gte: list[tuple[str, Any]] = []
        self._lte: list[tuple[str, Any]] = []
        self._in: dict[str, list[Any]] = {}
        self._order_desc = False
        self._limit: int | None = None
        self._maybe_single = False

    def select(self, cols: str) -> "_P2Table":
        return self

    def eq(self, col: str, val: Any) -> "_P2Table":
        self._filters.append((col, val))
        return self

    def gte(self, col: str, val: Any) -> "_P2Table":
        self._gte.append((col, val))
        return self

    def lte(self, col: str, val: Any) -> "_P2Table":
        self._lte.append((col, val))
        return self

    def in_(self, col: str, vals: list[Any]) -> "_P2Table":
        self._in[col] = vals
        return self

    def order(self, col: str, desc: bool = False) -> "_P2Table":
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "_P2Table":
        self._limit = n
        return self

    def maybe_single(self) -> "_P2Table":
        self._maybe_single = True
        return self

    def execute(self) -> "_P2Exec":
        if self._name == "athletes":
            return _P2Exec(self._db.athlete_row if self._maybe_single else [self._db.athlete_row])

        if self._name == "workouts":
            rows = self._filter_rows(self._db.workouts)
            if self._maybe_single:
                return _P2Exec(rows[0] if rows else None)
            return _P2Exec(rows)

        if self._name == "training_plans":
            rows = self._filter_rows(self._db.plans)
            if self._maybe_single:
                return _P2Exec(rows[0] if rows else None)
            return _P2Exec(rows)

        if self._name == "tss_history":
            rows = self._filter_rows(self._db.tss_history)
            rows.sort(key=lambda r: r.get("date", ""), reverse=self._order_desc)
            return _P2Exec(rows)

        if self._name == "biometrics":
            rows = self._filter_rows(self._db.biometrics)
            for col, vals in self._in.items():
                rows = [r for r in rows if r.get(col) in vals]
            rows.sort(key=lambda r: r.get("date", ""), reverse=self._order_desc)
            return _P2Exec(rows)

        return _P2Exec([])

    def _filter_rows(self, source: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = list(source)
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        for col, val in self._gte:
            rows = [r for r in rows if str(r.get(col, "")) >= str(val)]
        for col, val in self._lte:
            rows = [r for r in rows if str(r.get(col, "")) <= str(val)]
        if self._order_desc:
            rows.sort(key=lambda r: r.get("started_at", r.get("date", "")), reverse=True)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows


class _P2Exec:
    def __init__(self, data: Any):
        self.data = data


def _workout(
    wid: str,
    *,
    sport: str = "bike",
    started_at: str,
    duration_seconds: int = 3600,
    tss: float = 80.0,
) -> dict[str, Any]:
    end = datetime.fromisoformat(started_at.replace("Z", "+00:00")) + timedelta(seconds=duration_seconds)
    return {
        "id": wid,
        "athlete_id": "ath-1",
        "source": "manual",
        "primary_source": "manual",
        "sport": sport,
        "title": f"{sport} session",
        "started_at": started_at,
        "ended_at": end.isoformat(),
        "duration_seconds": duration_seconds,
        "distance_m": 30000,
        "avg_hr": 140,
        "max_hr": 170,
        "avg_power_w": 180,
        "norm_power_w": 190,
        "tss": tss,
        "strain_score": 50,
        "hr_zone_1_pct": 30,
        "hr_zone_2_pct": 40,
        "hr_zone_3_pct": 20,
        "hr_zone_4_pct": 10,
        "hr_zone_5_pct": 0,
    }


def test_list_planned_workouts_date_range():
    db = Phase2MockDB()
    db.plans = [
        {"id": "p1", "athlete_id": "ath-1", "planned_date": "2026-06-01", "sport": "bike", "title": "Ride", "duration_min": 90, "target_tss": 80, "primary_zone": "Endurance", "status": "planned"},
        {"id": "p2", "athlete_id": "ath-1", "planned_date": "2026-06-05", "sport": "run", "title": "Run", "duration_min": 45, "target_tss": 50, "primary_zone": "Tempo", "status": "planned"},
    ]
    out = coach_tools.handle_list_planned_workouts(
        {"start_date": "2026-06-01", "end_date": "2026-06-03"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["count"] == 1
    assert out["plans"][0]["sport"] == "bike"


def test_list_planned_workouts_invalid_range():
    db = Phase2MockDB()
    out = coach_tools.handle_list_planned_workouts(
        {"start_date": "2026-06-10", "end_date": "2026-06-01"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" in out


def test_get_training_load_series_default_window():
    db = Phase2MockDB()
    db.tss_history = [
        {"athlete_id": "ath-1", "date": "2026-05-28", "daily_tss": 50, "ctl": 40.0, "atl": 45.0, "tsb": -5.0},
        {"athlete_id": "ath-1", "date": "2026-05-29", "daily_tss": 80, "ctl": 41.0, "atl": 48.0, "tsb": -7.0},
    ]
    out = coach_tools.handle_get_training_load_series(
        {"start_date": "2026-05-28", "end_date": "2026-05-29"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["count"] == 2
    assert out["series"][1]["daily_tss"] == 80
    assert out["series"][1]["tsb"] == -7.0


def test_get_training_load_series_empty():
    db = Phase2MockDB()
    out = coach_tools.handle_get_training_load_series(
        {"start_date": "2026-01-01", "end_date": "2026-01-07"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["count"] == 0
    assert out["series"] == []


def test_get_biometrics_for_dates_found_and_missing():
    db = Phase2MockDB()
    db.biometrics = [
        {
            "date": "2026-05-28",
            "athlete_id": "ath-1",
            "hrv_rmssd": 55.0,
            "resting_hr": 48,
            "sleep_duration_min": 420,
            "recovery_score": 75,
            "strain_score": 40,
        }
    ]
    out = coach_tools.handle_get_biometrics_for_dates(
        {"dates": ["2026-05-28", "2026-05-29"]},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["count"] == 2
    assert out["days"][0]["hrv_rmssd"] == 55.0
    assert out["days"][1]["available"] is False


def test_get_biometrics_for_dates_too_many():
    db = Phase2MockDB()
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(8)]
    out = coach_tools.handle_get_biometrics_for_dates(
        {"dates": dates},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" in out


def test_get_biometrics_for_dates_requires_array():
    db = Phase2MockDB()
    out = coach_tools.handle_get_biometrics_for_dates(
        {},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["error"] == "dates array is required"


def test_summarize_workouts_week_period():
    db = Phase2MockDB()
    today = date.today()
    db.workouts = [
        _workout("w1", sport="bike", started_at=datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc).isoformat(), tss=100),
        _workout("w2", sport="run", started_at=(datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc) - timedelta(days=1)).isoformat(), tss=60),
    ]
    out = coach_tools.handle_summarize_workouts(
        {"period": "week"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["workout_count"] == 2
    assert out["total_tss"] == 160.0
    assert out["sport_mix"]["bike"] == 1
    assert out["sport_mix"]["run"] == 1
    assert out["hardest_session"]["id"] == "w1"


def test_summarize_workouts_custom_range_and_sport_filter():
    db = Phase2MockDB()
    db.workouts = [
        _workout("w1", sport="bike", started_at="2026-05-28T10:00:00+00:00", tss=90),
        _workout("w2", sport="run", started_at="2026-05-28T14:00:00+00:00", tss=40),
    ]
    out = coach_tools.handle_summarize_workouts(
        {"start_date": "2026-05-28", "end_date": "2026-05-28", "sport": "bike"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["workout_count"] == 1
    assert out["total_tss"] == 90.0


def test_summarize_workouts_invalid_period():
    db = Phase2MockDB()
    out = coach_tools.handle_summarize_workouts(
        {"period": "quarter"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" in out


def test_summarize_workouts_month_period():
    db = Phase2MockDB()
    out = coach_tools.handle_summarize_workouts(
        {"period": "month"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "start_date" in out
    assert out["workout_count"] == 0


def test_compare_workouts_deltas():
    db = Phase2MockDB()
    db.workouts = [
        _workout("w1", sport="bike", started_at="2026-05-20T10:00:00+00:00", tss=80, duration_seconds=3600),
        _workout("w2", sport="bike", started_at="2026-05-27T10:00:00+00:00", tss=100, duration_seconds=4200),
    ]
    out = coach_tools.handle_compare_workouts(
        {"workout_id_a": "w1", "workout_id_b": "w2"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["same_sport"] is True
    assert out["deltas_b_minus_a"]["tss"] == 20.0
    assert out["deltas_b_minus_a"]["duration_min"] == 10.0


def test_compare_workouts_missing_id():
    db = Phase2MockDB()
    out = coach_tools.handle_compare_workouts(
        {"workout_id_a": "w1"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["error"] == "workout_id_a and workout_id_b are required"


def test_compare_workouts_not_found():
    db = Phase2MockDB()
    out = coach_tools.handle_compare_workouts(
        {"workout_id_a": "w1", "workout_id_b": "w2"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["error"] == "workout_not_found"


def test_compare_workouts_different_sport():
    db = Phase2MockDB()
    db.workouts = [
        _workout("w1", sport="bike", started_at="2026-05-20T10:00:00+00:00"),
        _workout("w2", sport="run", started_at="2026-05-27T10:00:00+00:00"),
    ]
    out = coach_tools.handle_compare_workouts(
        {"workout_id_a": "w1", "workout_id_b": "w2"},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert out["same_sport"] is False


def test_phase2_handlers_registered():
    expected = {
        "list_planned_workouts",
        "get_training_load_series",
        "get_biometrics_for_dates",
        "summarize_workouts",
        "compare_workouts",
    }
    assert expected.issubset(set(coach_tools.TOOL_HANDLERS.keys()))


def test_resolve_date_range_end_before_start():
    db = Phase2MockDB()
    out = coach_workout_data.list_planned_workouts_compact(
        db,  # type: ignore[arg-type]
        "ath-1",
        {"start_date": "2026-06-10", "end_date": "2026-06-01"},
    )
    assert "error" in out


def test_training_load_series_end_before_start():
    db = Phase2MockDB()
    out = coach_workout_data.get_training_load_series(
        db,  # type: ignore[arg-type]
        "ath-1",
        {"start_date": "2026-06-10", "end_date": "2026-06-01"},
    )
    assert "error" in out


def test_summarize_workouts_hardest_session_none_when_empty():
    db = Phase2MockDB()
    out = coach_workout_data.summarize_workouts(
        db,  # type: ignore[arg-type]
        "ath-1",
        {"start_date": "2026-01-01", "end_date": "2026-01-07"},
    )
    assert out["hardest_session"] is None
    assert out["total_tss"] == 0.0
