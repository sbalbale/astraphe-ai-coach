from datetime import datetime

from app.models.schemas import ChatMessage, WorkoutPayload


def test_workout_payload_requires_core_fields_and_defaults_ftp():
    payload = WorkoutPayload(
        athlete_id="athlete-1",
        source="garmin",
        workout_type="cycling",
        start_time=datetime(2026, 5, 20, 10, 0, 0),
        duration_seconds=3600,
    )

    assert payload.ftp_at_time == 250
    assert payload.normalized_power is None
    assert payload.average_hr is None


def test_workout_payload_accepts_optional_power_and_hr():
    payload = WorkoutPayload(
        athlete_id="athlete-1",
        source="apple_health",
        workout_type="running",
        start_time="2026-05-20T10:00:00",
        duration_seconds=1800,
        normalized_power=210,
        average_hr=150,
        ftp_at_time=300,
    )

    assert payload.normalized_power == 210
    assert payload.average_hr == 150
    assert payload.ftp_at_time == 300


def test_chat_message_defaults_recent_tss_to_zero():
    message = ChatMessage(athlete_id="athlete-1", message="How was my week?")

    assert message.recent_tss == 0.0


def test_chat_message_accepts_explicit_recent_tss():
    message = ChatMessage(athlete_id="athlete-1", message="Hi", recent_tss=123.4)

    assert message.recent_tss == 123.4
