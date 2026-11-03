"""Interval structure the plan can show: decimal minutes and repeats expanded into blocks."""
from app.services import coach_tools as ct


def test_eight_by_ninety_seconds_becomes_visible_blocks():
    s = ct._sanitize_workout_structure(
        [
            {"name": "Warmup", "duration_minutes": 15, "target_hr_zone": 1},
            {
                "name": "Main Set",
                "repeat": 8,
                "sub_intervals": [
                    {"name": "Work", "duration_minutes": 1.5, "target_hr_zone": 5},
                    {"name": "Recovery", "duration_minutes": "1:30", "target_hr_zone": 1},
                ],
            },
            {"name": "Cooldown", "duration_minutes": 10, "target_hr_zone": 1},
        ]
    )
    names = [b["name"] for b in s]
    assert names[0] == "Warmup" and names[-1] == "Cooldown"
    assert names[1:3] == ["Work 1/8", "Recovery 1/8"] and names[-2] == "Recovery 8/8"
    assert len(s) == 2 + 16
    assert s[1]["duration_minutes"] == 1.5 and s[2]["duration_minutes"] == 1.5
    assert s[1]["target_hr_zone"] == 5
    assert all(b["sub_intervals"] == [] for b in s)


def test_whole_minutes_stay_integers():
    assert ct._minutes_value(15) == 15 and isinstance(ct._minutes_value(15.0), int)
    assert ct._minutes_value("0:45") == 0.75
    assert ct._minutes_value("x") == 0


def test_app_save_accepts_fractional_minutes():
    from app.routers.training_plans import IntervalPayload

    assert IntervalPayload(name="Work", duration_minutes=1.5).duration_minutes == 1.5
