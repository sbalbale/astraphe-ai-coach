from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from app.dependencies import get_admin_db, get_current_athlete, get_user_db
from app.main import app
from app.routers import sync as sync_router
from app.services import strava as strava_service
from app.services import whoop as whoop_service
from app.services import intervals_icu as intervals_icu_service


def _run_async(coro):
    return asyncio.run(coro)


def _override(athlete_id="athlete-1", user_db=None, admin_db=None):
    app.dependency_overrides[get_current_athlete] = lambda: athlete_id
    if user_db is not None:
        app.dependency_overrides[get_user_db] = lambda: user_db
    if admin_db is not None:
        app.dependency_overrides[get_admin_db] = lambda: admin_db


def _teardown():
    app.dependency_overrides = {}


client = TestClient(app)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_safe_web_return_allows_allowlisted_host():
    url = "https://app.astrapheai.com/x"
    assert sync_router._safe_web_return(url) == url


def test_safe_web_return_allows_subdomain():
    url = "https://staging.astrapheai.com/x"
    assert sync_router._safe_web_return(url) == url


def test_safe_web_return_rejects_unknown_host():
    assert sync_router._safe_web_return("https://evil.com/x") is None


def test_safe_web_return_none_or_empty():
    assert sync_router._safe_web_return(None) is None
    assert sync_router._safe_web_return("") is None


def test_safe_web_return_malformed_url_swallows_exception():
    assert sync_router._safe_web_return("http://[") is None


def test_get_clean_redirect_url():
    assert sync_router.get_clean_redirect_url().endswith("/v1/sync/oauth/whoop/callback")


def test_get_clean_strava_redirect_url():
    assert sync_router.get_clean_strava_redirect_url().endswith("/v1/sync/oauth/strava/callback")


def test_oauth_state_without_web_return():
    assert sync_router._oauth_state("ath-1", None) == "ath-1"


def test_oauth_state_with_safe_web_return():
    state = sync_router._oauth_state("ath-1", "https://app.astrapheai.com/x")
    assert state == "ath-1|https://app.astrapheai.com/x"


def test_oauth_state_with_unsafe_web_return_omits_it():
    assert sync_router._oauth_state("ath-1", "https://evil.com/x") == "ath-1"


def test_clean_intervals_athlete_id_strips():
    assert sync_router._clean_intervals_athlete_id("  123  ") == "123"


def test_clean_intervals_athlete_id_empty_raises():
    with pytest.raises(Exception):
        sync_router._clean_intervals_athlete_id("   ")


def test_clean_intervals_api_key_strips():
    assert sync_router._clean_intervals_api_key(" key ") == "key"


def test_clean_intervals_api_key_empty_raises():
    with pytest.raises(Exception):
        sync_router._clean_intervals_api_key("")


def test_build_whoop_oauth_authorize_url_contains_state():
    url = sync_router.build_whoop_oauth_authorize_url("ath-1", None)
    assert "state=ath-1" in url
    assert "client_id=" in url


def test_build_strava_oauth_authorize_url_contains_state():
    url = sync_router.build_strava_oauth_authorize_url("ath-1", None)
    assert "state=ath-1" in url
    assert "strava.com/oauth/authorize" in url


def test_oauth_connected_success_response_whoop():
    resp = sync_router._oauth_connected_success_response("astrapheai://x", "whoop")
    assert resp.status_code == 200
    assert b"WHOOP connected" in resp.body


def test_oauth_connected_success_response_strava():
    resp = sync_router._oauth_connected_success_response("astrapheai://x", "strava")
    assert b"Strava connected" in resp.body


def test_oauth_connected_success_response_unknown_provider_defaults_to_whoop():
    resp = sync_router._oauth_connected_success_response("astrapheai://x", "garmin")
    assert b"WHOOP connected" in resp.body


def test_webhook_int_none():
    assert sync_router._webhook_int(None) is None


def test_webhook_int_bool_rejected():
    assert sync_router._webhook_int(True) is None


def test_webhook_int_valid():
    assert sync_router._webhook_int("42") == 42


def test_webhook_int_invalid():
    assert sync_router._webhook_int("abc") is None


def test_map_garmin_sport_known():
    assert sync_router.map_garmin_sport("RUNNING") == "run"
    assert sync_router.map_garmin_sport("YOGA") == "mobility"


def test_map_garmin_sport_unknown():
    assert sync_router.map_garmin_sport("SOMETHING_ELSE") == "other"


def test_map_whoop_sport_string_variants():
    assert sync_router.map_whoop_sport("running") == "run"
    assert sync_router.map_whoop_sport("weight lifting") == "strength"
    assert sync_router.map_whoop_sport("cycling") == "bike"
    assert sync_router.map_whoop_sport("swim") == "swim"
    assert sync_router.map_whoop_sport("row") == "row"
    assert sync_router.map_whoop_sport("yoga") == "mobility"


def test_map_whoop_sport_numeric_string_falls_through_to_id_mapping():
    assert sync_router.map_whoop_sport("1") == "run"
    assert sync_router.map_whoop_sport("999") == "other"


def test_map_whoop_sport_unknown_string_is_other():
    assert sync_router.map_whoop_sport("underwater basket weaving") == "other"


def test_map_whoop_sport_int_id_mapping():
    assert sync_router.map_whoop_sport(8) == "bike"
    assert sync_router.map_whoop_sport(66) == "strength"
    assert sync_router.map_whoop_sport(70) == "swim"
    assert sync_router.map_whoop_sport(44) == "mobility"
    assert sync_router.map_whoop_sport(12345) == "other"


def test_map_whoop_sport_other_type_is_other():
    assert sync_router.map_whoop_sport(None) == "other"
    assert sync_router.map_whoop_sport(3.5) == "other"


def test_get_athlete_by_garmin_id_none_input():
    assert sync_router.get_athlete_by_garmin_id(MagicMock(), None) is None


def test_get_athlete_by_garmin_id_found():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "ath-1"}]
    )
    assert sync_router.get_athlete_by_garmin_id(db, "g1") == "ath-1"


def test_get_athlete_by_garmin_id_not_found():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    assert sync_router.get_athlete_by_garmin_id(db, "g1") is None


# ---------------------------------------------------------------------------
# _lookup_strava_owner_token
# ---------------------------------------------------------------------------


def test_lookup_strava_owner_token_success_first_try():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"athlete_id": "ath-1"}
    )
    result = _run_async(sync_router._lookup_strava_owner_token(db, 999))
    assert result.data == {"athlete_id": "ath-1"}


def test_lookup_strava_owner_token_retries_once_then_succeeds():
    query = MagicMock()
    query.execute.side_effect = [RuntimeError("transient"), SimpleNamespace(data={"athlete_id": "ath-1"})]
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = query

    with patch.object(sync_router.asyncio, "sleep", AsyncMock()):
        result = _run_async(sync_router._lookup_strava_owner_token(db, 999))
    assert result.data == {"athlete_id": "ath-1"}


def test_lookup_strava_owner_token_raises_after_two_failures():
    query = MagicMock()
    query.execute.side_effect = RuntimeError("permanent")
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value = query

    with patch.object(sync_router.asyncio, "sleep", AsyncMock()):
        with pytest.raises(RuntimeError, match="permanent"):
            _run_async(sync_router._lookup_strava_owner_token(db, 999))


# ---------------------------------------------------------------------------
# GET /v1/sync/strava/webhook (verify)
# ---------------------------------------------------------------------------


def test_strava_webhook_verify_success():
    with patch.object(sync_router.settings, "STRAVA_WEBHOOK_VERIFY_TOKEN", "secret-token"):
        res = client.get(
            "/v1/sync/strava/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "secret-token", "hub.challenge": "abc123"},
        )
    assert res.status_code == 200
    assert res.json() == {"hub.challenge": "abc123"}


def test_strava_webhook_verify_wrong_token_403():
    with patch.object(sync_router.settings, "STRAVA_WEBHOOK_VERIFY_TOKEN", "secret-token"):
        res = client.get(
            "/v1/sync/strava/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "abc123"},
        )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/sync/strava/webhook
# ---------------------------------------------------------------------------


def test_strava_webhook_invalid_json_returns_200():
    res = client.post("/v1/sync/strava/webhook", content=b"not json", headers={"content-type": "application/json"})
    assert res.status_code == 200


def test_strava_webhook_missing_owner_id_returns_200():
    res = client.post("/v1/sync/strava/webhook", json={"aspect_type": "create", "object_type": "activity"})
    assert res.status_code == 200


def test_strava_webhook_lookup_failure_returns_500():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = RuntimeError(
        "db down"
    )
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(sync_router.asyncio, "sleep", AsyncMock()):
            res = client.post(
                "/v1/sync/strava/webhook",
                json={"aspect_type": "create", "object_type": "activity", "object_id": 1, "owner_id": 999},
            )
        assert res.status_code == 500
    finally:
        _teardown()


def test_strava_webhook_unknown_owner_returns_200():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        res = client.post(
            "/v1/sync/strava/webhook",
            json={"aspect_type": "create", "object_type": "activity", "object_id": 1, "owner_id": 999},
        )
        assert res.status_code == 200
    finally:
        _teardown()


def test_strava_webhook_create_schedules_ingest():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"athlete_id": "ath-1"}
    )
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(strava_service, "ingest_strava_activity", AsyncMock()):
            res = client.post(
                "/v1/sync/strava/webhook",
                json={"aspect_type": "create", "object_type": "activity", "object_id": 111, "owner_id": 999},
            )
        assert res.status_code == 200
    finally:
        _teardown()


def test_strava_webhook_delete_clears_activity_id():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"athlete_id": "ath-1"}
    )
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        res = client.post(
            "/v1/sync/strava/webhook",
            json={"aspect_type": "delete", "object_type": "activity", "object_id": 111, "owner_id": 999},
        )
        assert res.status_code == 200
        admin_db.table.return_value.update.assert_called_once_with({"strava_activity_id": None})
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# GET /v1/sync/status
# ---------------------------------------------------------------------------


def test_get_sync_status_reports_connected_providers():
    user_db = MagicMock()
    user_db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"provider": "strava"}, {"provider": "whoop"}]
    )
    _override(user_db=user_db)
    try:
        res = client.get("/v1/sync/status")
        assert res.status_code == 200
        integrations = res.json()["integrations"]
        assert integrations["strava"]["connected"] is True
        assert integrations["whoop"]["connected"] is True
        assert integrations["garmin"]["connected"] is False
        assert integrations["healthkit"]["connected"] is False
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# DELETE /v1/sync/{provider}
# ---------------------------------------------------------------------------


def test_unlink_integration_missing_provider_400():
    _override(user_db=MagicMock())
    try:
        res = client.delete("/v1/sync/%20")
        assert res.status_code == 400
    finally:
        _teardown()


def test_unlink_integration_success_fully_removed():
    user_db = MagicMock()
    user_db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    user_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    _override(user_db=user_db)
    try:
        res = client.delete("/v1/sync/strava")
        assert res.status_code == 200
        body = res.json()
        assert body["connected"] is False
        assert "unlinked successfully" in body["message"]
    finally:
        _teardown()


def test_unlink_integration_still_connected_after_delete():
    user_db = MagicMock()
    user_db.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    user_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "tok-1"}]
    )
    _override(user_db=user_db)
    try:
        res = client.delete("/v1/sync/strava")
        assert res.status_code == 200
        body = res.json()
        assert body["connected"] is True
        assert "unlink requested" in body["message"]
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/refresh-strain
# ---------------------------------------------------------------------------


def test_refresh_strain_scores_now():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            sync_router, "refresh_all_daily_strain_sync", return_value={"updated": 3}
        ), patch.object(sync_router, "invalidate_context_cache") as mock_invalidate:
            res = client.post("/v1/sync/refresh-strain")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["updated"] == 3
        mock_invalidate.assert_called_once_with("athlete-1")
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/reprocess-metrics
# ---------------------------------------------------------------------------


def test_reprocess_metrics_now_default_is_strain_refresh():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            sync_router, "refresh_all_daily_strain_sync", return_value={"updated": 1}
        ), patch.object(sync_router, "invalidate_context_cache"):
            res = client.post("/v1/sync/reprocess-metrics")
        assert res.status_code == 200
        assert res.json()["mode"] == "strain_refresh"
    finally:
        _teardown()


def test_reprocess_metrics_now_full_success():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            sync_router, "reprocess_athlete_metrics", AsyncMock(return_value={"workouts": 5})
        ), patch.object(sync_router, "invalidate_context_cache"):
            res = client.post("/v1/sync/reprocess-metrics", params={"full": "true"})
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "full"
        assert body["workouts"] == 5
    finally:
        _teardown()


def test_reprocess_metrics_now_full_failure_returns_500():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(
            sync_router, "reprocess_athlete_metrics", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            res = client.post("/v1/sync/reprocess-metrics", params={"full": "true"})
        assert res.status_code == 500
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/whoop/backfill-biometrics
# ---------------------------------------------------------------------------


def test_whoop_backfill_biometrics_now_not_connected():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    _override(admin_db=admin_db)
    try:
        res = client.post("/v1/sync/whoop/backfill-biometrics")
        assert res.status_code == 400
    finally:
        _teardown()


def test_whoop_backfill_biometrics_now_success():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "tok"}
    )
    _override(admin_db=admin_db)
    try:
        with patch.object(sync_router, "backfill_biometrics_only", AsyncMock()):
            res = client.post("/v1/sync/whoop/backfill-biometrics", params={"days": 999})
        assert res.status_code == 200
        body = res.json()
        assert body["scheduled"] is True
        assert body["days"] == 365  # clamped
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/whoop/backfill
# ---------------------------------------------------------------------------


def test_whoop_backfill_now_not_connected():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    _override(user_db=MagicMock(), admin_db=admin_db)
    try:
        res = client.post("/v1/sync/whoop/backfill")
        assert res.status_code == 400
    finally:
        _teardown()


def test_whoop_backfill_now_success():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "tok"}
    )
    _override(user_db=MagicMock(), admin_db=admin_db)
    try:
        with patch.object(sync_router, "backfill_historical_data", AsyncMock()):
            res = client.post("/v1/sync/whoop/backfill", params={"days": 0})
        assert res.status_code == 200
        assert res.json()["days"] == 1  # clamped up
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/strava/backfill
# ---------------------------------------------------------------------------


def test_strava_backfill_now_not_connected():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(strava_service, "get_valid_token", AsyncMock(return_value=None)):
            res = client.post("/v1/sync/strava/backfill")
        assert res.status_code == 400
    finally:
        _teardown()


def test_strava_backfill_now_missing_strava_athlete_id():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    _override(admin_db=admin_db)
    try:
        with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")):
            res = client.post("/v1/sync/strava/backfill")
        assert res.status_code == 400
        assert "not found" in res.json()["detail"]
    finally:
        _teardown()


def test_strava_backfill_now_invalid_strava_athlete_id():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"external_user_id": "not-a-number"}
    )
    _override(admin_db=admin_db)
    try:
        with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")):
            res = client.post("/v1/sync/strava/backfill")
        assert res.status_code == 400
        assert "Invalid Strava athlete ID" in res.json()["detail"]
    finally:
        _teardown()


def test_strava_backfill_now_success():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"external_user_id": "999"}
    )
    _override(admin_db=admin_db)
    try:
        with patch.object(strava_service, "get_valid_token", AsyncMock(return_value="tok")), patch.object(
            sync_router, "strava_backfill", AsyncMock()
        ):
            res = client.post("/v1/sync/strava/backfill", params={"days": 30})
        assert res.status_code == 200
        assert res.json()["scheduled"] is True
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/intervals-icu/backfill
# ---------------------------------------------------------------------------


def test_intervals_icu_backfill_now_not_connected():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    _override(admin_db=admin_db)
    try:
        res = client.post("/v1/sync/intervals-icu/backfill")
        assert res.status_code == 400
    finally:
        _teardown()


def test_intervals_icu_backfill_now_success():
    admin_db = MagicMock()
    admin_db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"access_token": "key", "external_user_id": "123"}
    )
    _override(admin_db=admin_db)
    try:
        with patch.object(intervals_icu_service, "backfill_historical_data", AsyncMock()):
            res = client.post("/v1/sync/intervals-icu/backfill")
        assert res.status_code == 200
        assert res.json()["scheduled"] is True
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# POST /v1/sync/intervals-icu/connect
# ---------------------------------------------------------------------------


def test_intervals_icu_connect_success():
    admin_db = MagicMock()
    _override(admin_db=admin_db)
    try:
        with patch.object(intervals_icu_service, "verify_credentials", AsyncMock()), patch.object(
            sync_router, "_schedule_intervals_backfill"
        ) as mock_schedule:
            res = client.post(
                "/v1/sync/intervals-icu/connect",
                json={"intervals_athlete_id": "123", "api_key": "key", "days": 45},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["days"] == 45
        mock_schedule.assert_called_once()
    finally:
        _teardown()


def test_schedule_intervals_backfill_uses_background_tasks_when_present():
    bg = MagicMock()
    sync_router._schedule_intervals_backfill(bg, "ath-1", "123", "key", MagicMock(), 30)
    bg.add_task.assert_called_once()


def test_schedule_intervals_backfill_falls_back_to_create_task():
    async def _runner():
        with patch.object(sync_router.asyncio, "create_task") as mock_create_task:
            sync_router._schedule_intervals_backfill(None, "ath-1", "123", "key", MagicMock(), 30)
            mock_create_task.assert_called_once()

    _run_async(_runner())


# ---------------------------------------------------------------------------
# GET /v1/sync/oauth/whoop/authorize
# ---------------------------------------------------------------------------


def test_whoop_oauth_authorize_json_url():
    _override()
    try:
        res = client.get("/v1/sync/oauth/whoop/authorize", params={"json_url": "true"})
        assert res.status_code == 200
        assert "url" in res.json()
    finally:
        _teardown()


def test_whoop_oauth_authorize_redirect():
    _override()
    try:
        res = client.get("/v1/sync/oauth/whoop/authorize", follow_redirects=False)
        assert res.status_code in (302, 307)
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# GET /v1/sync/oauth/strava/authorize
# ---------------------------------------------------------------------------


def test_strava_oauth_authorize_not_configured_503():
    _override()
    try:
        with patch.object(sync_router.settings, "STRAVA_CLIENT_ID", ""):
            res = client.get("/v1/sync/oauth/strava/authorize")
        assert res.status_code == 503
    finally:
        _teardown()


def test_strava_oauth_authorize_json_url():
    _override()
    try:
        with patch.object(sync_router.settings, "STRAVA_CLIENT_ID", "id"), patch.object(
            sync_router.settings, "STRAVA_CLIENT_SECRET", "secret"
        ):
            res = client.get("/v1/sync/oauth/strava/authorize", params={"json_url": "true"})
        assert res.status_code == 200
        assert "url" in res.json()
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# GET /v1/sync/oauth/whoop/callback
# ---------------------------------------------------------------------------


def test_whoop_oauth_callback_missing_athlete_id_returns_error_dict():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            whoop_service, "exchange_oauth_code", AsyncMock(return_value={"access_token": "tok"})
        ):
            res = client.get(
                "/v1/sync/oauth/whoop/callback", params={"code": "abc", "state": "undefined"}
            )
        assert res.status_code == 200
        assert res.json()["status"] == "error"
    finally:
        _teardown()


def test_whoop_oauth_callback_success_html_response():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            whoop_service, "exchange_oauth_code", AsyncMock(return_value={"access_token": "tok", "refresh_token": "r"})
        ), patch.object(
            whoop_service, "fetch_profile", AsyncMock(return_value={"user_id": "wu-1"})
        ), patch.object(sync_router, "backfill_historical_data", AsyncMock()):
            res = client.get(
                "/v1/sync/oauth/whoop/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        assert b"WHOOP connected" in res.content
    finally:
        _teardown()


def test_whoop_oauth_callback_success_with_web_return_redirects():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            whoop_service, "exchange_oauth_code", AsyncMock(return_value={"access_token": "tok"})
        ), patch.object(
            whoop_service, "fetch_profile", AsyncMock(side_effect=RuntimeError("profile fetch failed"))
        ), patch.object(sync_router, "backfill_historical_data", AsyncMock()):
            res = client.get(
                "/v1/sync/oauth/whoop/callback",
                params={"code": "abc", "state": "ath-1|https://app.astrapheai.com/done"},
                follow_redirects=False,
            )
        assert res.status_code in (302, 307)
        assert "app.astrapheai.com" in res.headers["location"]
    finally:
        _teardown()


def test_whoop_oauth_callback_exchange_failure_returns_error_dict():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            whoop_service, "exchange_oauth_code", AsyncMock(side_effect=RuntimeError("exchange failed"))
        ):
            res = client.get(
                "/v1/sync/oauth/whoop/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        assert res.json()["status"] == "error"
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# GET /v1/sync/oauth/strava/callback
# ---------------------------------------------------------------------------


def test_strava_oauth_callback_missing_athlete_id_raises_400():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        res = client.get(
            "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "undefined"}
        )
        assert res.status_code == 400
    finally:
        _teardown()


def test_strava_oauth_callback_success():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            strava_service,
            "exchange_oauth_code",
            AsyncMock(return_value={"access_token": "tok", "refresh_token": "r", "athlete": {"id": 999}}),
        ), patch.object(
            strava_service, "strava_oauth_expires_at_iso", return_value=None
        ), patch.object(sync_router, "strava_backfill", AsyncMock()):
            res = client.get(
                "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        assert b"Strava connected" in res.content
    finally:
        _teardown()


def test_strava_oauth_callback_resolves_athlete_id_when_missing_from_token():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            strava_service,
            "exchange_oauth_code",
            AsyncMock(return_value={"access_token": "tok", "refresh_token": "r"}),
        ), patch.object(
            strava_service, "get_athlete_strava_id", AsyncMock(return_value=999)
        ), patch.object(
            strava_service, "strava_oauth_expires_at_iso", return_value=None
        ), patch.object(sync_router, "strava_backfill", AsyncMock()) as mock_backfill:
            res = client.get(
                "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        mock_backfill.assert_awaited_once()
    finally:
        _teardown()


def test_strava_oauth_callback_no_access_token_raises_400():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            strava_service, "exchange_oauth_code", AsyncMock(return_value={"access_token": None})
        ):
            res = client.get(
                "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 400
    finally:
        _teardown()


def test_strava_oauth_callback_unresolved_athlete_id_skips_backfill():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            strava_service,
            "exchange_oauth_code",
            AsyncMock(return_value={"access_token": "tok", "refresh_token": "r"}),
        ), patch.object(
            strava_service, "get_athlete_strava_id", AsyncMock(return_value=None)
        ), patch.object(
            strava_service, "strava_oauth_expires_at_iso", return_value=None
        ), patch.object(sync_router, "strava_backfill", AsyncMock()) as mock_backfill:
            res = client.get(
                "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        mock_backfill.assert_not_awaited()
    finally:
        _teardown()


def test_strava_oauth_callback_unexpected_error_returns_error_dict():
    admin_db = MagicMock()
    app.dependency_overrides[get_admin_db] = lambda: admin_db
    try:
        with patch.object(
            strava_service, "exchange_oauth_code", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            res = client.get(
                "/v1/sync/oauth/strava/callback", params={"code": "abc", "state": "ath-1"}
            )
        assert res.status_code == 200
        assert res.json()["status"] == "error"
    finally:
        _teardown()
