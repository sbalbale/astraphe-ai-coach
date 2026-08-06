from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_admin_db, get_current_athlete
from app.main import app
from app.routers import garmin_sync
from app.services import garmin as garmin_service

client = TestClient(app)


def _override(admin_db=None):
    app.dependency_overrides[get_current_athlete] = lambda: "athlete-1"
    if admin_db is not None:
        app.dependency_overrides[get_admin_db] = lambda: admin_db


def _teardown():
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# _schedule_backfill / _persist_and_schedule (direct unit tests)
# ---------------------------------------------------------------------------


def test_schedule_backfill_uses_background_tasks_when_present():
    bg = MagicMock()
    db = MagicMock()
    garmin_sync._schedule_backfill(bg, "ath-1", db, 30)
    bg.add_task.assert_called_once_with(garmin_service.backfill_historical_data, "ath-1", db, 30)


def test_schedule_backfill_falls_back_to_create_task():
    import asyncio

    async def _runner():
        with patch.object(garmin_sync.asyncio, "create_task") as mock_create_task:
            garmin_sync._schedule_backfill(None, "ath-1", MagicMock(), 30)
            mock_create_task.assert_called_once()

    asyncio.run(_runner())


def test_persist_and_schedule_uses_client_display_name():
    client_obj = MagicMock(display_name="garmin-user-1")
    admin_db = MagicMock()
    bg = MagicMock()
    with patch.object(garmin_service, "persist_session") as mock_persist:
        result = garmin_sync._persist_and_schedule(client_obj, "ath-1", admin_db, bg, 45)
    mock_persist.assert_called_once_with(admin_db, "ath-1", client_obj, "garmin-user-1")
    assert result == {
        "status": "success",
        "provider": "garmin",
        "connected": True,
        "scheduled": True,
        "days": 45,
    }


# ---------------------------------------------------------------------------
# POST /v1/sync/garmin/connect
# ---------------------------------------------------------------------------


def test_garmin_connect_success():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        fake_client = MagicMock(display_name="garmin-user-1")
        with patch.object(
            garmin_service, "login", return_value=fake_client
        ), patch.object(garmin_service, "persist_session") as mock_persist, patch.object(
            garmin_sync, "_schedule_backfill"
        ) as mock_schedule:
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2", "days": 60},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["days"] == 60
        mock_persist.assert_called_once()
        mock_schedule.assert_called_once()
    finally:
        _teardown()


def test_garmin_connect_mfa_required():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "login", side_effect=garmin_service.GarminMfaRequired("state-tok-1")
        ):
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["mfa_required"] is True
        assert body["state_token"] == "state-tok-1"
    finally:
        _teardown()


def test_garmin_connect_rate_limited():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "login", side_effect=garmin_service.GarminRateLimitedError("slow down")
        ):
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2"},
            )
        assert res.status_code == 429
        assert "slow down" in res.json()["detail"]
    finally:
        _teardown()


def test_garmin_connect_rate_limited_default_message():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(garmin_service, "login", side_effect=garmin_service.GarminRateLimitedError()):
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2"},
            )
        assert res.status_code == 429
        assert "try again later" in res.json()["detail"]
    finally:
        _teardown()


def test_garmin_connect_auth_error():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "login", side_effect=garmin_service.GarminAuthError("bad password")
        ):
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2"},
            )
        assert res.status_code == 401
        assert "bad password" in res.json()["detail"]
    finally:
        _teardown()


def test_garmin_connect_unexpected_error_returns_502_without_leaking_detail():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(garmin_service, "login", side_effect=RuntimeError("some internal secret path")):
            res = client.post(
                "/v1/sync/garmin/connect",
                json={"username": "sean@example.com", "password": "hunter2"},
            )
        assert res.status_code == 502
        assert "internal secret path" not in res.json()["detail"]
        assert res.json()["detail"] == "Garmin connect failed"
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/garmin/connect/mfa
# ---------------------------------------------------------------------------


def test_garmin_connect_mfa_success():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        fake_client = MagicMock(display_name="garmin-user-1")
        with patch.object(
            garmin_service, "resume_mfa", return_value=fake_client
        ), patch.object(garmin_service, "persist_session"), patch.object(
            garmin_sync, "_schedule_backfill"
        ):
            res = client.post(
                "/v1/sync/garmin/connect/mfa",
                json={"state_token": "state-tok-1", "mfa_code": "123456"},
            )
        assert res.status_code == 200
        assert res.json()["status"] == "success"
    finally:
        _teardown()


def test_garmin_connect_mfa_rate_limited():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "resume_mfa", side_effect=garmin_service.GarminRateLimitedError("slow down")
        ):
            res = client.post(
                "/v1/sync/garmin/connect/mfa",
                json={"state_token": "state-tok-1", "mfa_code": "123456"},
            )
        assert res.status_code == 429
    finally:
        _teardown()


def test_garmin_connect_mfa_auth_error():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "resume_mfa", side_effect=garmin_service.GarminAuthError("bad code")
        ):
            res = client.post(
                "/v1/sync/garmin/connect/mfa",
                json={"state_token": "state-tok-1", "mfa_code": "123456"},
            )
        assert res.status_code == 401
        assert "bad code" in res.json()["detail"]
    finally:
        _teardown()


def test_garmin_connect_mfa_unexpected_error_returns_502():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(garmin_service, "resume_mfa", side_effect=RuntimeError("boom")):
            res = client.post(
                "/v1/sync/garmin/connect/mfa",
                json={"state_token": "state-tok-1", "mfa_code": "123456"},
            )
        assert res.status_code == 502
        assert res.json()["detail"] == "Garmin MFA failed"
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/garmin/backfill
# ---------------------------------------------------------------------------


def test_garmin_backfill_now_not_connected():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(garmin_service, "get_client_for_athlete", return_value=None):
            res = client.post("/v1/sync/garmin/backfill")
        assert res.status_code == 400
        assert "not connected" in res.json()["detail"]
    finally:
        _teardown()


def test_garmin_backfill_now_success_clamps_days():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            garmin_service, "get_client_for_athlete", return_value=MagicMock()
        ), patch.object(garmin_service, "backfill_historical_data", AsyncMock()):
            res = client.post("/v1/sync/garmin/backfill", params={"days": 9999})
        assert res.status_code == 200
        body = res.json()
        assert body["scheduled"] is True
        assert body["days"] == 365
    finally:
        _teardown()
