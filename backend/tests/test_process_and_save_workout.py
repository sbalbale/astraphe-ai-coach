from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.workout import WorkoutPayload
from app.services import processing


def _run_async(coro):
    return asyncio.run(coro)


def _base_payload(**overrides) -> WorkoutPayload:
    base = dict(
        source="manual",
        sport="run",
        started_at="2026-05-20T10:00:00Z",
        duration_seconds=1800,
    )
    base.update(overrides)
    return WorkoutPayload(**base)


def _patch_common(row=None, athlete=None, created=False):
    row = row or {"id": "w1"}
    athlete = athlete if athlete is not None else {}
    return (
        patch.object(
            processing, "find_or_create_canonical_workout", AsyncMock(return_value=(row, created))
        ),
        patch.object(processing, "_fetch_athlete_for_workout_sync", return_value=athlete),
        patch.object(processing, "_workouts_update_by_id_sync"),
    )


def test_process_and_save_workout_bike_normalized_power_branch():
    payload = _base_payload(sport="cycling", normalized_power=200, ftp_at_time=250)
    p1, p2, p3 = _patch_common()
    with p1, p2, p3 as mock_update:
        workout_id = _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )

    assert workout_id == "w1"
    update_data = mock_update.call_args[0][2]
    assert update_data["tss"] > 0
    assert update_data["sport"] == "bike"


def test_process_and_save_workout_run_pace_branch():
    payload = _base_payload(sport="run", avg_pace_sec_km=300)
    athlete = {"threshold_pace": "5:00"}
    p1, p2, p3 = _patch_common(athlete=athlete)
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )

    update_data = mock_update.call_args[0][2]
    assert update_data["tss"] > 0


def test_process_and_save_workout_hr_zones_branch():
    payload = _base_payload(
        sport="run",
        avg_hr=150,
        hr_zone_1_pct=10,
        hr_zone_2_pct=40,
        hr_zone_3_pct=30,
        hr_zone_4_pct=15,
        hr_zone_5_pct=5,
    )
    athlete = {"max_hr": 190, "resting_hr": 50, "threshold_hr": 165, "threshold_hr_source": "manual"}
    p1, p2, p3 = _patch_common(athlete=athlete)
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )

    update_data = mock_update.call_args[0][2]
    assert update_data["tss"] > 0
    assert update_data["strain_score"] > 0


def test_process_and_save_workout_rowing_branch():
    payload = _base_payload(sport="row", average_power=200, ftp_at_time=250)
    p1, p2, p3 = _patch_common()
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )

    update_data = mock_update.call_args[0][2]
    assert update_data["tss"] > 0


def test_process_and_save_workout_explicit_tss_fallback():
    payload = _base_payload(sport="strength", tss=42.0)
    p1, p2, p3 = _patch_common()
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )

    update_data = mock_update.call_args[0][2]
    assert update_data["tss"] == 42.0


def test_process_and_save_workout_normalizes_gym_and_yoga_sport_aliases():
    payload = _base_payload(sport="gym")
    p1, p2, p3 = _patch_common()
    with p1 as mock_find, p2, p3:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )
    # canonical sport passed to the dedup resolver should be "strength", not "gym".
    assert mock_find.call_args[0][3] == "strength"


def test_process_and_save_workout_computes_ended_at_from_duration():
    payload = _base_payload(duration_seconds=1800, ended_at=None)
    p1, p2, p3 = _patch_common()
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )
    update_data = mock_update.call_args[0][2]
    started = datetime.fromisoformat(update_data["started_at"])
    ended = datetime.fromisoformat(update_data["ended_at"])
    assert (ended - started) == timedelta(seconds=1800)


def test_process_and_save_workout_schedules_background_recalc_when_not_skipped():
    payload = _base_payload()
    p1, p2, p3 = _patch_common()
    with p1, p2, p3, patch.object(
        processing, "recalculate_tss_history", MagicMock()
    ) as mock_recalc, patch.object(
        processing, "_refresh_daily_strain_for_day_sync", MagicMock()
    ) as mock_strain:

        async def _run_and_drain():
            await processing.process_and_save_workout(payload, "athlete-1", MagicMock())
            # Let the fire-and-forget asyncio.ensure_future tasks actually run.
            await asyncio.sleep(0.05)

        _run_async(_run_and_drain())

    mock_recalc.assert_called_once()
    mock_strain.assert_called_once()
