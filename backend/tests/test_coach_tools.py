"""Unit tests for agentic coach tools and anomaly detection."""
from __future__ import annotations

import json
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
    struct = row["structure"]
    assert len(struct) >= 3
    assert "name" in struct[0] and struct[0]["name"]
    assert "duration_minutes" in struct[0]
    assert "sub_intervals" in struct[0]
    assert isinstance(struct[0]["sub_intervals"], list)
    assert "phase" not in struct[0]
    main = struct[1]
    assert main["name"].lower() == "main"
    assert len(main["sub_intervals"]) >= 2
    assert out["garmin_push"]["status"] == "stubbed"
    # 45 min * 1.1^2 * (45/60) * 100 ≈ 90.75 TSS
    assert 85 <= float(out["target_tss_estimate"]) <= 95
    strict = out.get("workout_strict") or {}
    assert strict.get("id") == "mock-plan-id"
    assert strict.get("date") == planned
    assert strict.get("sport") == "bike"
    assert strict.get("primary_zone") == "VO2Max"


def test_schedule_workout_mobility_uses_bodyweight_structure():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=2)).isoformat()
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 30,
            "focus_zone": "Recovery",
            "date": planned,
            "sport": "yoga",
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    assert db.inserts and db.inserts[0][0] == "training_plans"
    row = db.inserts[0][1]
    assert row["sport"] == "mobility"
    struct = row.get("structure") or []
    assert isinstance(struct, list) and len(struct) >= 1
    assert "target_watts" not in struct[0]
    assert "name" in struct[0]
    assert "phase" not in struct[0]


def test_sanitize_workout_structure_maps_hallucinated_keys():
    raw = [
        {"phase": "warmup", "duration_min": 10, "description": "Easy spin"},
        {
            "name": "Main set",
            "duration": 30,
            "intervals": [{"type": "work", "duration_min": 3, "target_hr_zone": 5}],
        },
    ]
    out = coach_tools._sanitize_workout_structure(raw)
    assert out[0]["name"] == "Warmup"
    assert out[0]["duration_minutes"] == 10
    assert "phase" not in out[0]
    assert out[1]["name"] == "Main set"
    assert out[1]["duration_minutes"] == 30
    assert len(out[1]["sub_intervals"]) == 1
    sub = out[1]["sub_intervals"][0]
    assert sub["name"] == "Work"
    assert sub["duration_minutes"] == 3
    assert sub["target_hr_zone"] == 5


def test_schedule_workout_optional_ai_structure_override():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=3)).isoformat()
    custom = [
        {
            "phase": "main",
            "duration_min": 40,
            "description": "Custom main",
            "intervals": [
                {"type": "work", "duration_min": 5, "target_power_percent_ftp": 95},
                {"type": "recovery", "duration_min": 2},
            ],
        }
    ]
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 45,
            "focus_zone": "Endurance",
            "date": planned,
            "sport": "bike",
            "structure": custom,
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    row = db.inserts[0][1]
    struct = row["structure"]
    assert len(struct) == 1
    b = struct[0]
    assert b["name"] == "Main"
    assert b["duration_minutes"] == 40
    assert b["description"] == "Custom main"
    assert len(b["sub_intervals"]) == 2
    assert b["sub_intervals"][0]["name"] == "Work"
    assert b["sub_intervals"][0]["target_power_percent_ftp"] == 95
    assert b["sub_intervals"][1]["name"] == "Recovery"


def test_schedule_workout_empty_structure_list_keeps_generated():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=4)).isoformat()
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 45,
            "focus_zone": "VO2Max",
            "date": planned,
            "sport": "Bike",
            "structure": [],
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    row = db.inserts[0][1]
    assert len(row["structure"]) >= 3


def test_schedule_workout_markdown_notes_stores_description():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=5)).isoformat()
    md = "| Interval | Watts |\n|----------|-------|\n| Warmup | 150 |"
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 45,
            "focus_zone": "Endurance",
            "date": planned,
            "sport": "bike",
            "markdown_notes": md,
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    row = db.inserts[0][1]
    assert row["description"] == md


def test_schedule_workout_normalizes_escaped_newlines_in_markdown_notes():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=5)).isoformat()
    escaped = (
        "| Phase | Duration | Intensity | Target |\\n"
        "| :--- | :--- | :--- | :--- |\\n"
        "| Warmup | 10 min | Z1-Z2 | Easy spin |"
    )
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 60,
            "focus_zone": "Endurance",
            "date": planned,
            "sport": "bike",
            "markdown_notes": escaped,
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    row = db.inserts[0][1]
    assert "\\n" not in row["description"]
    assert "| Phase | Duration | Intensity | Target |" in row["description"]
    assert "\n| Warmup | 10 min | Z1-Z2 | Easy spin |" in row["description"]


def test_schedule_workout_without_markdown_notes_keeps_json_description():
    db = MockCoachDB()
    planned = (date.today() + timedelta(days=6)).isoformat()
    out = coach_tools.handle_schedule_workout(
        {
            "duration_minutes": 45,
            "focus_zone": "VO2Max",
            "date": planned,
            "sport": "Bike",
            "markdown_notes": "   ",
        },
        athlete_id="ath-1",
        db=db,  # type: ignore[arg-type]
    )
    assert "error" not in out
    row = db.inserts[0][1]
    parsed = json.loads(row["description"])
    assert parsed["sport"] == "bike"
    assert parsed["focus_zone"] == "VO2Max"
    assert isinstance(parsed["structure"], list)


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
                "skin_temp": 0.0,
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
