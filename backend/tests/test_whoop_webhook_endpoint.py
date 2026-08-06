from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_admin_db
from app.main import app
from app.routers import sync as sync_router
from app.services import whoop as whoop_service

client = TestClient(app)


def _override(admin_db):
    app.dependency_overrides[get_admin_db] = lambda: admin_db


def _teardown():
    app.dependency_overrides = {}


def _token_row(**overrides):
    row = {
        "athlete_id": "ath-1",
        "access_token": "tok",
        "refresh_token": "refresh-tok",
        "provider": "whoop",
        "external_user_id": "999",
    }
    row.update(overrides)
    return row


def _db_with_token(token_row=None, athlete_tz_offset=0):
    """
    A MagicMock db whose db.table(...) returns per-table configured chains
    for the whoop_webhook handler's oauth_tokens lookup + athletes timezone
    lookup (both .execute() and .single().execute()/.maybe_single().execute()
    variants are used across the three event-type branches).
    """
    db = MagicMock()

    def _table(name):
        m = MagicMock()
        if name == "oauth_tokens":
            # initial SELECT * ... .execute() (no maybe_single/single)
            m.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
                data=[token_row] if token_row else []
            )
            # _refresh_and_persist_token's re-read: .single().execute()
            m.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
                data=token_row
            )
        elif name == "athletes":
            tz_data = {"timezone_offset_min": athlete_tz_offset}
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
                data=tz_data
            )
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
                data=tz_data
            )
        elif name == "biometrics":
            m.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
                data={"weight_kg": 70.0}
            )
        return m

    db.table.side_effect = _table
    return db


def _patch_background_targets():
    """
    Patches every function whoop_webhook() might schedule via
    background_tasks.add_task(...) -- TestClient actually executes background
    tasks as part of the response cycle, so anything unmocked here either
    needs a real return value or (for _whoop_retry_recovery_vitals, which
    sleeps for WHOOP_RECOVERY_RETRY_DELAYS_SEC = 120s/600s between attempts)
    risks a multi-minute hang.
    """
    return (
        patch.object(sync_router, "process_and_save_biometrics", MagicMock()),
        patch.object(sync_router, "process_and_save_workout", AsyncMock()),
        patch.object(sync_router, "_whoop_sync_whoop_body_measurements", AsyncMock()),
        patch.object(sync_router, "_whoop_retry_recovery_vitals", AsyncMock()),
    )


# ---------------------------------------------------------------------------
# Signature verification / envelope handling
# ---------------------------------------------------------------------------


def test_whoop_webhook_missing_signature_401():
    db = _db_with_token()
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", False):
            res = client.post("/v1/sync/whoop/webhook", json={"type": "recovery.updated"})
        assert res.status_code == 401
    finally:
        _teardown()


def test_whoop_webhook_invalid_json_returns_200():
    db = _db_with_token()
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True):
            res = client.post(
                "/v1/sync/whoop/webhook", content=b"not json", headers={"content-type": "application/json"}
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_unknown_user_returns_200():
    db = _db_with_token(token_row=None)
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True):
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "recovery.updated", "user_id": 999, "data": {"id": 1}},
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_log_raw_body_does_not_break_request():
    db = _db_with_token(token_row=None)
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            sync_router.settings, "WHOOP_WEBHOOK_LOG_RAW", True
        ):
            res = client.post(
                "/v1/sync/whoop/webhook", json={"type": "recovery.updated", "user_id": 999}
            )
        assert res.status_code == 200
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# recovery.updated
# ---------------------------------------------------------------------------


def test_whoop_webhook_recovery_updated_no_event_id_returns_200():
    db = _db_with_token(_token_row())
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True):
            res = client.post(
                "/v1/sync/whoop/webhook", json={"type": "recovery.updated", "user_id": 999, "data": {}}
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_recovery_updated_success_schedules_biometrics_and_body_sync():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_recovery_for_event_id", AsyncMock(return_value={"created_at": "2026-05-20T10:00:00Z"})
        ), patch.object(
            whoop_service, "build_whoop_vitals_from_recovery", return_value={"recovery_score": 80}
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "recovery.updated", "user_id": 999, "data": {"id": 12345}},
            )
            assert res.status_code == 200
            sync_router.process_and_save_biometrics.assert_called_once()
            sync_router._whoop_sync_whoop_body_measurements.assert_awaited_once()
    finally:
        _teardown()


def test_whoop_webhook_recovery_updated_no_recovery_data_returns_200():
    db = _db_with_token(_token_row())
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_recovery_for_event_id", AsyncMock(return_value=None)
        ):
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "recovery.updated", "user_id": 999, "data": {"id": 12345}},
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_recovery_updated_uses_sleep_end_date_for_uuid_event_id():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_sleep_data", AsyncMock(return_value={"end": "2026-05-20T10:00:00Z"})
        ), patch.object(
            whoop_service, "fetch_recovery_for_sleep", AsyncMock(return_value={"created_at": "2026-05-20T10:00:00Z"})
        ), patch.object(
            whoop_service, "build_whoop_vitals_from_recovery", return_value={}
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "recovery.updated", "user_id": 999, "data": {"id": "sleep-uuid-1"}},
            )
        assert res.status_code == 200
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# sleep.updated
# ---------------------------------------------------------------------------


def _sleep_data(**overrides):
    base = {
        "id": 555,
        "start": "2026-05-20T02:00:00Z",
        "end": "2026-05-20T10:00:00Z",
        "nap": False,
        "score": {
            "sleep_performance_percentage": 85,
            "stage_summary": {
                "total_light_sleep_time_milli": 3_600_000,
                "total_slow_wave_sleep_time_milli": 1_800_000,
                "total_rem_sleep_time_milli": 1_200_000,
                "total_awake_time_milli": 300_000,
            },
        },
    }
    base.update(overrides)
    return base


def test_whoop_webhook_sleep_updated_no_event_id_returns_200():
    db = _db_with_token(_token_row())
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True):
            res = client.post(
                "/v1/sync/whoop/webhook", json={"type": "sleep.updated", "user_id": 999, "data": {}}
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_sleep_updated_success_with_recovery_merged():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_sleep_data", AsyncMock(return_value=_sleep_data())
        ), patch.object(
            # event_id (555) is numeric, so _whoop_fetch_recovery_with_refresh's
            # "not str(event_id).isdigit()" branch is False -> it calls
            # fetch_recovery_for_event_id, not fetch_recovery_for_sleep.
            whoop_service,
            "fetch_recovery_for_event_id",
            AsyncMock(return_value={"created_at": "2026-05-20T10:00:00Z"}),
        ), patch.object(
            whoop_service, "build_whoop_vitals_from_recovery", return_value={"recovery_score": 70}
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "sleep.updated", "user_id": 999, "data": {"id": 555}},
            )
            assert res.status_code == 200
            sync_router.process_and_save_biometrics.assert_called_once()
            sync_router._whoop_retry_recovery_vitals.assert_not_awaited()
    finally:
        _teardown()


def test_whoop_webhook_sleep_updated_no_recovery_schedules_retry():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_sleep_data", AsyncMock(return_value=_sleep_data())
        ), patch.object(
            whoop_service, "fetch_recovery_for_sleep", AsyncMock(return_value=None)
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "sleep.updated", "user_id": 999, "data": {"id": 555}},
            )
            assert res.status_code == 200
            sync_router._whoop_retry_recovery_vitals.assert_awaited_once()
    finally:
        _teardown()


def test_whoop_webhook_sleep_updated_nap_skips_recovery_fetch():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_sleep_data", AsyncMock(return_value=_sleep_data(nap=True))
        ), patch.object(
            whoop_service, "fetch_recovery_for_sleep", AsyncMock()
        ) as mock_recovery, patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "sleep.updated", "user_id": 999, "data": {"id": 555}},
            )
        assert res.status_code == 200
        mock_recovery.assert_not_awaited()
    finally:
        _teardown()


def test_whoop_webhook_sleep_updated_401_refreshes_and_retries():
    db = _db_with_token(_token_row())
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service,
            "fetch_sleep_data",
            AsyncMock(side_effect=[HTTPException(status_code=401), _sleep_data()]),
        ), patch.object(
            whoop_service, "refresh_oauth_token", AsyncMock(return_value={"access_token": "new-tok"})
        ), patch.object(
            whoop_service, "fetch_recovery_for_sleep", AsyncMock(return_value=None)
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "sleep.updated", "user_id": 999, "data": {"id": 555}},
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_sleep_updated_401_no_refresh_token_swallowed():
    db = _db_with_token(_token_row(refresh_token=None))
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_sleep_data", AsyncMock(side_effect=HTTPException(status_code=401))
        ):
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "sleep.updated", "user_id": 999, "data": {"id": 555}},
            )
        # The outer try/except in whoop_webhook catches the re-raised 401 and returns 200.
        assert res.status_code == 200
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# workout.updated
# ---------------------------------------------------------------------------


def _workout_data(**overrides):
    base = {
        "id": 777,
        "start": "2026-05-20T10:00:00Z",
        "end": "2026-05-20T11:00:00Z",
        "sport_name": "running",
        "score": {
            "distance_meter": 10000,
            "average_heart_rate": 145,
            "max_heart_rate": 172,
            "zone_durations": {},
        },
    }
    base.update(overrides)
    return base


def test_whoop_webhook_workout_updated_no_event_id_returns_200():
    db = _db_with_token(_token_row())
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True):
            res = client.post(
                "/v1/sync/whoop/webhook", json={"type": "workout.updated", "user_id": 999, "data": {}}
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_whoop_webhook_workout_updated_success_schedules_body_sync_when_weight_missing():
    db = _db_with_token(_token_row())

    # Override the "biometrics" branch to report weight_kg missing for this test.
    def _table(name):
        m = MagicMock()
        if name == "oauth_tokens":
            m.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
                data=[_token_row()]
            )
        elif name == "athletes":
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
                data={"timezone_offset_min": 0}
            )
        elif name == "biometrics":
            m.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
                data=None
            )
        return m

    db.table.side_effect = _table
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_workout_data", AsyncMock(return_value=_workout_data())
        ), patch.object(
            whoop_service, "hr_zone_pct_from_whoop_zone_millis", return_value=(10, 20, 30, 30, 10)
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "workout.updated", "user_id": 999, "data": {"id": 777}},
            )
            assert res.status_code == 200
            sync_router.process_and_save_workout.assert_awaited_once()
            sync_router._whoop_sync_whoop_body_measurements.assert_awaited_once()
    finally:
        _teardown()


def test_whoop_webhook_workout_updated_skips_body_sync_when_weight_present():
    db = _db_with_token(_token_row(), athlete_tz_offset=0)  # biometrics returns weight_kg=70.0
    _override(db)
    patches = _patch_background_targets()
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_workout_data", AsyncMock(return_value=_workout_data())
        ), patch.object(
            whoop_service, "hr_zone_pct_from_whoop_zone_millis", return_value=(10, 20, 30, 30, 10)
        ), patches[0], patches[1], patches[2], patches[3]:
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "workout.updated", "user_id": 999, "data": {"id": 777}},
            )
            assert res.status_code == 200
            sync_router._whoop_sync_whoop_body_measurements.assert_not_awaited()
    finally:
        _teardown()


def test_whoop_webhook_generic_exception_swallowed_returns_200():
    db = _db_with_token(_token_row())
    _override(db)
    try:
        with patch.object(sync_router.settings, "WHOOP_WEBHOOK_SKIP_SIG_CHECK", True), patch.object(
            whoop_service, "fetch_workout_data", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            res = client.post(
                "/v1/sync/whoop/webhook",
                json={"type": "workout.updated", "user_id": 999, "data": {"id": 777}},
            )
        assert res.status_code == 200
    finally:
        _teardown()
