"""Regression tests for the data-pipeline fixes found in the metric audit."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import anchor_history, garmin, processing
from app.services.algorithms import NEUROMUSCULAR_MULTIPLIER, compute_strain_score
from tests.test_process_and_save_biometrics import _BioDb, _default_responses, _payload


def _run(coro):
    return asyncio.run(coro)


# --- Garmin sport mapping -------------------------------------------------------------------------


def test_any_garmin_rowing_key_is_a_row_and_unknown_keys_stay_other():
    """27 on-water rows came through with an unmapped rowing key and were stored as 'other'."""
    assert garmin.map_garmin_connect_sport("rowing") == "row"
    assert garmin.map_garmin_connect_sport("rowing_v2") == "row"
    assert garmin.map_garmin_connect_sport("indoor_rowing") == "row"
    assert garmin.map_garmin_connect_sport("pickleball") == "other"
    assert garmin.map_garmin_connect_sport(None) == "other"


# --- Garmin multisport --------------------------------------------------------------------------


# Shapes from Garmin for the 2026-09-09 East Hartford Multisport (erg + transition + run).
_PARENT_LIST_ENTRY = {
    "activityId": 24300692825,
    "activityName": "East Hartford Multisport",
    "activityType": {"typeKey": "multi_sport"},
    "parent": True,
    "isParent": True,
    "startTimeGMT": "2026-09-09 17:24:44",
    "duration": 2633.8,
}
_PARENT_DETAIL = {
    "activityId": 24300692825,
    "metadataDTO": {
        "childIds": [24300692603, 24300692604, 24300692605],
        "childActivityTypes": ["indoor_rowing", "transition_v2", "running"],
    },
}
_LEGS = {
    24300692603: {
        "activityId": 24300692603,
        "activityName": "Indoor Rowing",
        "activityTypeDTO": {"typeKey": "indoor_rowing"},
        "summaryDTO": {"startTimeGMT": "2026-09-09T17:24:44.0", "duration": 1190.196, "distance": 0.0, "averageHR": 169.0, "maxHR": 180.0},
    },
    24300692605: {
        "activityId": 24300692605,
        "activityName": "Running",
        "activityTypeDTO": {"typeKey": "running"},
        "summaryDTO": {
            "startTimeGMT": "2026-09-09T17:45:11.0", "duration": 1407.171, "distance": 4596.18,
            "averageHR": 178.0, "maxHR": 184.0, "averageSpeed": 3.266,
        },
    },
}


def _client():
    c = MagicMock()
    c.get_activity.side_effect = lambda aid: _PARENT_DETAIL if int(aid) == 24300692825 else _LEGS[int(aid)]
    return c


def test_multisport_parent_is_recognised_and_its_legs_skip_transitions():
    assert garmin.is_multisport_parent(_PARENT_LIST_ENTRY)
    assert not garmin.is_multisport_parent({"activityType": {"typeKey": "running"}, "parent": False})
    assert garmin.multisport_leg_ids(_client(), 24300692825) == [24300692603, 24300692605]


def test_a_leg_maps_to_a_normal_workout_payload():
    p = garmin.build_workout_payload(garmin.leg_as_list_activity(_LEGS[24300692605]))
    assert p.workout_type == "run"
    assert p.garmin_activity_id == 24300692605
    assert p.start_time == datetime(2026, 9, 9, 17, 45, 11, tzinfo=timezone.utc)
    assert p.duration_seconds == 1407
    assert p.average_hr == 178
    assert p.avg_pace_sec_km == pytest.approx(306, abs=1)
    erg = garmin.build_workout_payload(garmin.leg_as_list_activity(_LEGS[24300692603]))
    assert erg.workout_type == "row"


def test_split_multisport_deletes_the_parent_and_returns_only_missing_legs():
    db = MagicMock()
    with patch.object(garmin, "_stored_garmin_ids", return_value={24300692603}), patch.object(
        garmin, "_delete_garmin_parent", return_value=1
    ) as delete, patch.object(garmin, "GARMIN_REQUEST_GAP_S", 0):
        legs = _run(garmin.split_multisport(_client(), db, "a", 24300692825))
    delete.assert_called_once_with(db, "a", 24300692825)
    assert [leg["activityId"] for leg in legs] == [24300692605]  # the erg is already stored


def test_the_sync_stores_legs_instead_of_the_parent():
    saved: list = []

    async def _save(client, activity, athlete_id, db):
        saved.append(activity["activityId"])
        return True, False

    async def _split(client, db, athlete_id, parent_id):
        return [garmin.leg_as_list_activity(_LEGS[24300692603]), garmin.leg_as_list_activity(_LEGS[24300692605])]

    client = MagicMock()
    client.get_activities_by_date.return_value = [_PARENT_LIST_ENTRY]
    with patch.object(garmin, "get_client_for_athlete", return_value=client), patch.object(
        garmin, "_save_one_activity", side_effect=_save
    ), patch.object(garmin, "split_multisport", side_effect=_split), patch.object(
        garmin, "persist_session"
    ), patch.object(garmin, "recompute_workout_tss_for_athlete", MagicMock(return_value=asyncio.sleep(0))), patch.object(
        garmin, "recalculate_tss_history"
    ), patch.object(garmin, "GARMIN_REQUEST_GAP_S", 0):
        try:
            _run(garmin.sync_activities_for_athlete("a", MagicMock(), date(2026, 9, 9), date(2026, 9, 9)))
        except Exception:
            pass  # later steps (caches etc.) aren't under test here
    assert saved == [24300692603, 24300692605]


# --- TSS / strain stuck at 0 ----------------------------------------------------------------------


def test_a_stored_zero_tss_or_strain_can_be_filled_by_a_lower_ranked_source():
    """12 workouts with HR zones stayed at TSS 0: their primary source (Garmin) outranks the
    provider that recomputed them, and the filter only let new values fill None."""
    row = {"primary_source": "garmin", "tss": 0.0, "strain_score": 0, "avg_hr": 150}
    out = processing._quality_filter_workout_update(row, "whoop", {"tss": 36.8, "strain_score": 22, "avg_hr": 140})
    assert out["tss"] == 36.8
    assert out["strain_score"] == 22
    assert "avg_hr" not in out  # real values keep the usual source priority


def test_a_real_tss_is_only_replaced_by_a_lower_ranked_source_when_recomputing():
    row = {"primary_source": "garmin", "tss": 48.0}
    assert "tss" not in processing._quality_filter_workout_update(row, "strava", {"tss": 38.3})
    assert processing._quality_filter_workout_update(row, "strava", {"tss": 38.3}, recompute=True)["tss"] == 38.3


# --- Strength strain ----------------------------------------------------------------------------


def test_daily_strain_counts_strength_with_the_neuromuscular_multiplier():
    lift = {"sport": "strength", "duration_seconds": 3600, "hr_zone_1_pct": 50, "hr_zone_2_pct": 50}
    ride = dict(lift, sport="bike")
    day_strength = processing._compute_daily_strain_from_workout_rows([lift])
    day_ride = processing._compute_daily_strain_from_workout_rows([ride])
    assert day_strength > day_ride
    assert day_strength == compute_strain_score({1: 30.0, 2: 30.0, 3: 0, 4: 0, 5: 0}, sport="strength")
    assert NEUROMUSCULAR_MULTIPLIER > 1


def test_a_new_strength_workout_gets_the_multiplier_from_any_provider():
    from tests.test_process_and_save_workout import _base_payload, _patch_common

    payload = _base_payload(source="strava", sport="strength", hr_zone_1_pct=50, hr_zone_2_pct=50)
    p1, p2, p3 = _patch_common(created=True)
    with p1, p2, p3 as upd:
        _run(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    zm = {1: 15.0, 2: 15.0, 3: 0.0, 4: 0.0, 5: 0.0}
    assert upd.call_args[0][2]["strain_score"] == compute_strain_score(zm, sport="strength")


# --- Sleep without stages -----------------------------------------------------------------------


def _unstaged_night(deep, rem, light):
    period = {
        "in_bed_min": 743, "duration_min": 698, "awake_pct": 6.1,
        "deep_pct": deep, "rem_pct": rem, "light_pct": light,
        "started_at": "2026-08-18T23:00:00Z", "ended_at": "2026-08-19T11:23:00Z",
    }
    db = _BioDb(_default_responses(sleep_periods=[SimpleNamespace(data=None), SimpleNamespace(data=[period])]))
    payload = _payload(
        date=date(2026, 8, 19),
        sleep_bedtime=datetime(2026, 8, 18, 23, 0, tzinfo=timezone.utc),
        sleep_wakeup=datetime(2026, 8, 19, 11, 23, tzinfo=timezone.utc),
        sleep_deep_pct=deep, sleep_rem_pct=rem, sleep_light_pct=light, sleep_awake_pct=6.1,
    )
    processing.process_and_save_biometrics(payload, "athlete-1", db, skip_pmc_recalc=True)
    return db.upserts["biometrics"][0]


def test_a_night_with_zero_deep_and_rem_gets_the_backup_score_not_the_penalty():
    """2026-08-19: Garmin sent 11.6 h asleep with deep / REM 0 (unstaged); the strict formula's
    0.25 'no restorative sleep' penalty scored it 11."""
    row = _unstaged_night(0.0, 0.0, 100.0)
    assert row["metric_sources"]["sleep_score"] == "astraphe_backup"
    assert row["sleep_score"] >= 70


def test_a_night_with_no_stage_data_keeps_stages_empty():
    row = _unstaged_night(None, None, None)
    assert row["sleep_deep_pct"] is None
    assert row["sleep_rem_pct"] is None
    assert row["metric_sources"]["sleep_score"] == "astraphe_backup"


def test_a_staged_night_still_uses_the_architecture_score():
    row = _unstaged_night(18.0, 22.0, 60.0)
    assert row["metric_sources"]["sleep_score"] == "astraphe"


# --- Anchor (FTP / threshold pace) history ------------------------------------------------------


_HISTORY = [
    {"effective_from": "1900-01-01", "ftp_watts": 280, "threshold_pace": "8:00", "measurement_units": "imperial"},
    {"effective_from": "2026-11-10", "ftp_watts": 255, "threshold_pace": "8:00", "measurement_units": "imperial"},
]


def test_a_workout_uses_the_anchors_in_effect_on_its_date():
    profile = {"ftp_watts": 255, "threshold_pace": "8:00", "measurement_units": "imperial"}
    assert anchor_history.anchors_on(_HISTORY, date(2026, 11, 4), profile)["ftp_watts"] == 280
    assert anchor_history.anchors_on(_HISTORY, date(2026, 11, 10), profile)["ftp_watts"] == 255
    assert anchor_history.anchors_on([], date(2026, 11, 4), profile)["ftp_watts"] == 255  # no history: profile


def test_local_day_uses_the_athletes_offset():
    # 00:15 UTC on Jul 10 is 19:15 on Jul 9 in EST (-300).
    assert anchor_history.local_day("2026-07-10T00:15:00+00:00", -300) == date(2026, 7, 9)


def test_a_synced_ride_is_scored_with_the_ftp_on_its_date():
    from tests.test_process_and_save_workout import _base_payload, _patch_common

    payload = _base_payload(source="garmin", sport="bike", duration_seconds=3600, normalized_power=200,
                            started_at="2026-11-04T18:00:00Z")
    p1, p2, p3 = _patch_common(athlete={"ftp_watts": 255, "timezone_offset_min": -300}, created=True)
    with p1, p2, p3 as upd, patch.object(anchor_history, "load_history", return_value=_HISTORY):
        _run(processing.process_and_save_workout(payload, "a", MagicMock(), skip_tss_recalc=True, skip_daily_strain_refresh=True))
    assert upd.call_args[0][2]["tss"] == pytest.approx(3600 * 200 * (200 / 280) / (280 * 3600) * 100)
