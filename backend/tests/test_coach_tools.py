"""Unit tests for agentic coach tools and anomaly detection."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.services import coach_tools
from app.services.ai_coach import detect_anomalies
class _Exec:
    __slots__ = ("data",)

    def __init__(self, data: Any):
        self.data = data


class MockCoachDB:
    """Minimal Supabase-like chain for coach_tools + detect_anomalies."""

    def __init__(self):
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.tss_rows: list[dict[str, Any]] = []
        self.athlete_row: dict[str, Any] = {
            "ftp_watts": 250,
            "threshold_hr": 165,
            "max_hr": 192,
            "resting_hr": 48,
            "threshold_pace": "5:00",
            "display_name": "Test",
        }
        self.bio_rows_30: list[dict[str, Any]] = []
        self.bio_rows_14: list[dict[str, Any]] = []

    def table(self, name: str) -> "_Table":
        return _Table(self, name)


class _Table:
    def __init__(self, db: MockCoachDB, name: str):
        self._db = db
        self._name = name
        self._limit: int | None = None
        self._cols: str = ""

    def select(self, cols: str) -> "_Table":
        self._cols = cols
        return self

    def eq(self, *args: Any, **kwargs: Any) -> "_Table":
        return self

    def order(self, *args: Any, **kwargs: Any) -> "_Table":
        return self

    def gte(self, *args: Any, **kwargs: Any) -> "_Table":
        return self

    def limit(self, n: int) -> "_Table":
        self._limit = n
        return self

    def maybe_single(self) -> "_Table":
        return self

    def insert(self, row: dict[str, Any]) -> "_Insert":
        return _Insert(self._db, self._name, row)

    def execute(self) -> _Exec:
        if self._name == "tss_history":
            if self._limit == 1 and "ctl" in self._cols and "daily_tss" not in self._cols:
                return _Exec([{"ctl": 70.0}])
            return _Exec(list(self._db.tss_rows))
        if self._name == "athletes":
            return _Exec(self._db.athlete_row)
        if self._name == "biometrics":
            if self._limit == 30:
                return _Exec(list(self._db.bio_rows_30))
            return _Exec(list(self._db.bio_rows_14))
        return _Exec([])


class _Insert:
    def __init__(self, db: MockCoachDB, name: str, row: dict[str, Any]):
        self._db = db
        self._name = name
        self._row = row

    def execute(self) -> _Exec:
        self._db.inserts.append((self._name, dict(self._row)))
        return _Exec([{"id": "mock-plan-id"}])


def test_simulate_training_impact_projection():
    today = date.today()
    # History: 10 days ending yesterday at 40 TSS/day
    hist: list[dict[str, Any]] = []
    for i in range(10, 0, -1):
        d = today - timedelta(days=i)
        hist.append({"date": d.isoformat(), "daily_tss": 40.0})
    db = MockCoachDB()
    db.tss_rows = hist

    target = today + timedelta(days=4)
    out = coach_tools.handle_simulate_training_impact(
        {"target_tss": 150, "target_date": target.isoformat()},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    assert out["today_tss_assumed"] == 150
    assert out["days_out"] == 4
    assert "projected_ctl" in out and "projected_atl" in out and "projected_tsb" in out
    assert out["projected_tsb"] == pytest.approx(
        round(float(out["projected_ctl"]) - float(out["projected_atl"]), 2), abs=0.02
    )


def test_calculate_nutrition_three_hour_endurance():
    db = MockCoachDB()
    db.tss_rows = [{"date": date.today().isoformat(), "daily_tss": 0, "ctl": 72.0, "atl": 60.0, "tsb": 12.0}]

    out = coach_tools.handle_calculate_nutrition(
        {"estimated_duration_minutes": 180, "estimated_tss": 180},
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    assert out["carb_g_per_hour"] == 80.0
    kj = float(out["kj"])
    assert 580 <= kj <= 720  # ~648 at ctl_factor ~1.007 for CTL 72
    assert out["total_carb_g"] == pytest.approx(240.0, rel=0.01)


def test_schedule_workout_vo2max_inserts_training_plan():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=1)).isoformat()
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 45,
            "focus_zone": "VO2Max",
            "date": planned,
            "sport": "Bike",
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    assert out.get("training_plan_id") == "mock-plan-id"
    assert db.inserts and db.inserts[0][0] == "training_plans"
    row = db.inserts[0][1]
    assert row["duration_min"] == 45
    assert row["status"] == "planned"
    assert row["primary_zone"] == "VO2Max"
    assert isinstance(row.get("structure"), list)
    assert out["garmin_push"]["status"] == "stubbed"
    # 45 min * 1.1^2 * (45/60) * 100 ≈ 90.75 TSS
    assert 85 <= float(out["target_tss_estimate"]) <= 95
    strict = out.get("workout_strict") or {}
    assert strict.get("id") == "mock-plan-id"
    assert strict.get("date") == planned
    assert strict.get("sport") == "cycling"
    assert strict.get("primary_zone") == "VO2Max"


def test_detect_anomalies_hrv_suppressed():
    today = date.today()
    # order(date desc): row 0 = today (suppressed HRV), older days stable at 50 ms
    desc_rows: list[dict[str, Any]] = []
    for i in range(30):
        d = today - timedelta(days=i)
        desc_rows.append(
            {
                "date": d.isoformat(),
                # Baseline must not be perfectly flat or EWMA std collapses and z=0.
                "hrv_rmssd": 15.0 if i == 0 else (48.0 + (i % 7) * 0.4),
                "resting_hr": 50,
                "sleep_duration_min": 480,
                "sleep_debt_min": 0,
                "skin_temp_deviation": 0.0,
            }
        )
    db = MockCoachDB()
    db.bio_rows_30 = desc_rows
    db.bio_rows_14 = desc_rows[:14]

    db.tss_rows = [{"date": today.isoformat(), "daily_tss": 0, "ctl": 60, "atl": 50, "tsb": -5}]

    an = detect_anomalies(db, "ath-1")  # type: ignore[arg-type]
    assert an is not None
    assert an.get("triggered") is True
    sigs = an.get("signals") or []
    assert any(s.get("metric") == "hrv_z" for s in sigs)
