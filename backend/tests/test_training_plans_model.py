"""Training plan payload normalization (mobile / coach parity)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.training_plans import WorkoutPayload


def test_workout_payload_mobility_canonical():
    w = WorkoutPayload(
        date="2026-05-10",
        title="Flow",
        sport="Mobility",
        primary_zone="Recovery",
        duration_minutes=30,
        projected_tss=12,
    )
    assert w.sport == "mobility"


def test_workout_payload_legacy_cycling_to_bike():
    w = WorkoutPayload(
        date="2026-05-10",
        title="Ride",
        sport="cycling",
        primary_zone="Endurance",
        duration_minutes=60,
        projected_tss=50,
    )
    assert w.sport == "bike"


def test_workout_payload_unknown_sport_becomes_other():
    w = WorkoutPayload(
        date="2026-05-10",
        title="X",
        sport="kayak",
        primary_zone="Recovery",
        duration_minutes=20,
        projected_tss=5,
    )
    assert w.sport == "other"


def test_workout_payload_rejects_negative_duration():
    with pytest.raises(ValidationError):
        WorkoutPayload(
            date="2026-05-10",
            title="X",
            sport="run",
            primary_zone="Recovery",
            duration_minutes=-1,
            projected_tss=0,
        )
