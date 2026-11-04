from __future__ import annotations
import pytest

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
        processing, "_refresh_daily_strain_for_instant_sync", MagicMock()
    ) as mock_strain:

        async def _run_and_drain():
            await processing.process_and_save_workout(payload, "athlete-1", MagicMock())
            # Let the fire-and-forget asyncio.ensure_future tasks actually run.
            await asyncio.sleep(0.05)

        _run_async(_run_and_drain())

    mock_recalc.assert_called_once()
    mock_strain.assert_called_once()


def test_process_and_save_workout_normalizes_yoga_to_mobility():
    payload = _base_payload(sport="yoga")
    p1, p2, p3 = _patch_common()
    with p1 as mock_find, p2, p3:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )
    assert mock_find.call_args[0][3] == "mobility"


def test_process_and_save_workout_computes_duration_from_ended_at():
    payload = _base_payload(duration_seconds=None, ended_at="2026-05-20T10:30:00Z")
    p1, p2, p3 = _patch_common()
    with p1, p2, p3 as mock_update:
        _run_async(
            processing.process_and_save_workout(
                payload, "athlete-1", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True
            )
        )
    update_data = mock_update.call_args[0][2]
    assert update_data["duration_seconds"] == 1800


# --- Re-sync of an existing workout (e.g. the Garmin poll's 2-day window) -------------------------

_STREAMED_RIDE = {
    "id": "w1",
    "source": "garmin",
    "primary_source": "garmin",
    "strain_score": 0,  # already reset by the bug; the stored zones still say ~32
    "tss": 48.0,
    "hr_zone_1_pct": 17,
    "hr_zone_2_pct": 80,
}


def test_resync_without_zones_recomputes_strain_from_stored_zones():
    """Production: a ride's strain went to 0 because the 15-min re-poll saved Garmin's
    zone-less summary over the strain its FIT stream had given it."""
    payload = _base_payload(source="garmin", sport="indoor_cycling", avg_hr=149, duration_seconds=3610)
    p1, p2, p3 = _patch_common(row=dict(_STREAMED_RIDE))
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    update_data = mock_update.call_args[0][2]
    assert update_data["strain_score"] == processing.compute_strain_score(
        {1: 0.17 * 3610 / 60, 2: 0.80 * 3610 / 60, 3: 0, 4: 0, 5: 0}, sport="bike"
    )
    assert update_data["strain_score"] > 0
    assert "tss" not in update_data  # a 0.0 the summary can't derive doesn't replace 48


def test_resync_without_any_zones_keeps_the_stored_strain():
    row = {"id": "w1", "source": "garmin", "primary_source": "garmin", "strain_score": 12, "tss": 20.0}
    payload = _base_payload(source="garmin", sport="strength", duration_seconds=1800)
    p1, p2, p3 = _patch_common(row=row)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    update_data = mock_update.call_args[0][2]
    assert "strain_score" not in update_data
    assert "tss" not in update_data


def test_new_workout_without_zones_still_starts_at_zero():
    payload = _base_payload(source="garmin", sport="strength", duration_seconds=1800)
    p1, p2, p3 = _patch_common(created=True)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    update_data = mock_update.call_args[0][2]
    assert update_data["strain_score"] == 0
    assert update_data["tss"] == 0.0


# --- Power TSS uses the athlete's FTP --------------------------------------------------------------


def _ride(**kw):
    return _base_payload(source="garmin", sport="bike", duration_seconds=3610, normalized_power=173, **kw)


def test_synced_ride_is_scored_with_the_profile_ftp():
    """Production: every synced ride was scored against a hardcoded FTP 250 (TSS 48.0 for a ride
    that is 38.3 at the athlete's 280 W), because no sync source set ftp_at_time."""
    p1, p2, p3 = _patch_common(athlete={"ftp_watts": 280}, created=True)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(_ride(), "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    assert mock_update.call_args[0][2]["tss"] == pytest.approx(3610 * 173 * (173 / 280) / (280 * 3600) * 100)


def test_an_ftp_given_with_the_workout_wins_over_the_profile():
    p1, p2, p3 = _patch_common(athlete={"ftp_watts": 280}, created=True)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(_ride(ftp_at_time=255), "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    assert mock_update.call_args[0][2]["tss"] == pytest.approx(3610 * 173 * (173 / 255) / (255 * 3600) * 100)


def test_without_any_ftp_power_is_not_scored_and_heart_rate_is():
    payload = _ride(avg_hr=149, hr_zone_1_pct=17, hr_zone_2_pct=80, hr_zone_3_pct=3)
    athlete = {"max_hr": 204, "resting_hr": 52, "threshold_hr": 185, "threshold_hr_source": "manual"}
    p1, p2, p3 = _patch_common(athlete=athlete, created=True)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    hr_only = processing.compute_hrss_from_zones(
        zone_minutes={1: 0.17 * 3610 / 60, 2: 0.80 * 3610 / 60, 3: 0.03 * 3610 / 60, 4: 0.0, 5: 0.0},
        max_hr=204, resting_hr=52, threshold_hr=185, sport="bike", gender="male",
        threshold_hr_source="manual", hr_zone_method=None,
    )
    assert mock_update.call_args[0][2]["tss"] == pytest.approx(hr_only)


def test_erg_power_uses_the_profile_ftp():
    payload = _base_payload(source="garmin", sport="rowing", duration_seconds=3600, avg_power_w=200)
    p1, p2, p3 = _patch_common(athlete={"ftp_watts": 280}, created=True)
    with p1, p2, p3 as mock_update:
        _run_async(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    np_ = 200 * 1.12
    assert mock_update.call_args[0][2]["tss"] == pytest.approx(3600 * int(np_) * (int(np_) / 280) / (280 * 3600) * 100)


def test_workout_ftp_ignores_missing_and_zero_values():
    assert processing.workout_ftp(None, 280) == 280
    assert processing.workout_ftp(255, 280) == 255
    assert processing.workout_ftp(0, None) is None
    assert processing.workout_ftp(None, "290") == 290
