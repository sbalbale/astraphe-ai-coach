from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import sync


# ---------------------------------------------------------------------------
# Web-return / OAuth state helpers
# ---------------------------------------------------------------------------


def test_safe_web_return_allows_allowlisted_hosts():
    assert sync._safe_web_return("https://app.astrapheai.com/dashboard") is not None
    assert sync._safe_web_return("https://astrapheai.com/x") is not None
    assert sync._safe_web_return("https://localhost:3000/x") is not None
    assert sync._safe_web_return("https://sub.astrapheai.com/x") is not None  # wildcard suffix


def test_safe_web_return_rejects_unlisted_host():
    assert sync._safe_web_return("https://evil.com/x") is None


def test_safe_web_return_handles_none_and_malformed():
    assert sync._safe_web_return(None) is None
    assert sync._safe_web_return("") is None


def test_get_clean_redirect_url_and_strava_variant(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://api.astrapheai.com/")
    monkeypatch.setattr(settings, "API_PREFIX", "/v1")
    assert sync.get_clean_redirect_url() == "https://api.astrapheai.com/v1/sync/oauth/whoop/callback"
    assert sync.get_clean_strava_redirect_url() == "https://api.astrapheai.com/v1/sync/oauth/strava/callback"


def test_oauth_state_appends_valid_web_return():
    state = sync._oauth_state("athlete-1", "https://app.astrapheai.com/x")
    assert state == "athlete-1|https://app.astrapheai.com/x"


def test_oauth_state_ignores_invalid_web_return():
    assert sync._oauth_state("athlete-1", "https://evil.com/x") == "athlete-1"
    assert sync._oauth_state("athlete-1", None) == "athlete-1"


# ---------------------------------------------------------------------------
# Intervals.icu payload cleaning
# ---------------------------------------------------------------------------


def test_clean_intervals_athlete_id_requires_value():
    try:
        sync._clean_intervals_athlete_id("  ")
        assert False
    except HTTPException as e:
        assert e.status_code == 400


def test_clean_intervals_athlete_id_strips():
    assert sync._clean_intervals_athlete_id("  i123  ") == "i123"


def test_clean_intervals_api_key_requires_value():
    try:
        sync._clean_intervals_api_key("")
        assert False
    except HTTPException as e:
        assert e.status_code == 400


def test_clean_intervals_api_key_strips():
    assert sync._clean_intervals_api_key("  secret  ") == "secret"


def test_schedule_intervals_backfill_uses_background_tasks_when_provided():
    bg = MagicMock()
    sync._schedule_intervals_backfill(bg, "athlete-1", "iid", "key", MagicMock(), 90)
    bg.add_task.assert_called_once()


def test_schedule_intervals_backfill_creates_task_without_background_tasks():
    with patch.object(sync.asyncio, "create_task") as mock_create_task, patch.object(
        sync.intervals_icu_service, "backfill_historical_data", return_value=MagicMock()
    ):
        sync._schedule_intervals_backfill(None, "athlete-1", "iid", "key", MagicMock(), 90)
    mock_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# OAuth URL builders
# ---------------------------------------------------------------------------


def test_build_whoop_oauth_authorize_url_includes_state_and_client_id(monkeypatch):
    monkeypatch.setattr(settings, "WHOOP_CLIENT_ID", "whoop-client")
    url = sync.build_whoop_oauth_authorize_url("athlete-1")
    assert "client_id=whoop-client" in url
    assert "state=athlete-1" in url


def test_build_strava_oauth_authorize_url_includes_state_and_client_id(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "strava-client")
    url = sync.build_strava_oauth_authorize_url("athlete-1", "https://app.astrapheai.com/x")
    assert "client_id=strava-client" in url
    assert "state=athlete-1" in url
    assert "www.strava.com/oauth/authorize" in url


# ---------------------------------------------------------------------------
# WHOOP body measurement parsing
# ---------------------------------------------------------------------------


def test_coerce_float_rejects_bool_and_non_positive():
    assert sync._coerce_float(True) is None
    assert sync._coerce_float(-5) is None
    assert sync._coerce_float(0) is None
    assert sync._coerce_float("5.5") == 5.5
    assert sync._coerce_float("abc") is None
    assert sync._coerce_float(None) is None


def test_parse_whoop_height_cm_prefers_cm_over_meters_over_inches():
    assert sync._parse_whoop_height_cm({"height_cm": 180}, None) == 180
    assert sync._parse_whoop_height_cm({"height_m": 1.8}, None) == 180.0
    assert sync._parse_whoop_height_cm({"height_in": 70}, None) == 70 * 2.54


def test_parse_whoop_height_cm_reads_nested_measurements():
    assert sync._parse_whoop_height_cm(None, {"measurements": {"height_cm": 175}}) == 175


def test_parse_whoop_height_cm_returns_none_without_data():
    assert sync._parse_whoop_height_cm(None, None) is None
    assert sync._parse_whoop_height_cm("not-a-dict", None) is None


def test_parse_whoop_weight_kg_prefers_kg_over_lbs():
    assert sync._parse_whoop_weight_kg(None, {"weight_kg": 70}) == 70
    result = sync._parse_whoop_weight_kg(None, {"weight_lbs": 154.0})
    assert round(result, 1) == 69.9


def test_parse_whoop_weight_kg_reads_nested_measurements():
    assert sync._parse_whoop_weight_kg({"measurements": {"weight_kg": 68}}, None) == 68


def test_parse_whoop_weight_kg_returns_none_without_data():
    assert sync._parse_whoop_weight_kg(None, None) is None


def test_whoop_local_date_from_iso_applies_offset():
    result = sync._whoop_local_date_from_iso("2026-05-20T23:30:00Z", -240)
    assert result == date(2026, 5, 20)


def test_whoop_local_date_from_iso_returns_none_for_invalid_input():
    assert sync._whoop_local_date_from_iso(None, 0) is None
    assert sync._whoop_local_date_from_iso("not-a-date", 0) is None


def test_whoop_biometrics_weight_kg_missing_true_on_exception():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        RuntimeError("db down")
    )
    assert sync._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 20)) is True


def test_whoop_biometrics_weight_kg_missing_true_without_row():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data=None
    )
    assert sync._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 20)) is True


def test_whoop_biometrics_weight_kg_missing_false_when_present():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"weight_kg": 70}
    )
    assert sync._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 20)) is False


# ---------------------------------------------------------------------------
# Webhook int coercion / Garmin & WHOOP sport mapping
# ---------------------------------------------------------------------------


def test_webhook_int_handles_bool_and_invalid():
    assert sync._webhook_int(True) is None
    assert sync._webhook_int(None) is None
    assert sync._webhook_int("abc") is None
    assert sync._webhook_int("123") == 123
    assert sync._webhook_int(123) == 123


def test_get_athlete_by_garmin_id_returns_none_for_blank():
    assert sync.get_athlete_by_garmin_id(MagicMock(), "") is None


def test_get_athlete_by_garmin_id_returns_athlete_id():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"athlete_id": "athlete-1"}]
    )
    assert sync.get_athlete_by_garmin_id(db, "garmin-1") == "athlete-1"


def test_get_athlete_by_garmin_id_returns_none_when_not_found():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    assert sync.get_athlete_by_garmin_id(db, "garmin-1") is None


def test_map_garmin_sport_known_and_unknown():
    assert sync.map_garmin_sport("RUNNING") == "run"
    assert sync.map_garmin_sport("YOGA") == "mobility"
    assert sync.map_garmin_sport("UNKNOWN_SPORT") == "other"


def test_map_whoop_sport_string_names():
    assert sync.map_whoop_sport("weightlifting") == "strength"
    assert sync.map_whoop_sport("Running") == "run"
    assert sync.map_whoop_sport("cycling") == "bike"
    assert sync.map_whoop_sport("swimming") == "swim"
    assert sync.map_whoop_sport("rowing") == "row"
    assert sync.map_whoop_sport("yoga") == "mobility"
    assert sync.map_whoop_sport("something_else") == "other"


def test_map_whoop_sport_numeric_string_falls_through_to_id_mapping():
    assert sync.map_whoop_sport("1") == "run"
    assert sync.map_whoop_sport("8") == "bike"
    assert sync.map_whoop_sport("999") == "other"


def test_map_whoop_sport_int_id_mapping():
    assert sync.map_whoop_sport(1) == "run"
    assert sync.map_whoop_sport(66) == "strength"
    assert sync.map_whoop_sport(44) == "mobility"
    assert sync.map_whoop_sport(9999) == "other"


def test_map_whoop_sport_unrecognized_type_returns_other():
    assert sync.map_whoop_sport(None) == "other"
    assert sync.map_whoop_sport([1, 2]) == "other"


# ---------------------------------------------------------------------------
# strava_webhook_verify endpoint
# ---------------------------------------------------------------------------


def test_strava_webhook_verify_success(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_VERIFY_TOKEN", "secret-token")
    with TestClient(app) as client:
        res = client.get(
            "/v1/sync/strava/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "secret-token", "hub.challenge": "xyz"},
        )
    assert res.status_code == 200
    assert res.json() == {"hub.challenge": "xyz"}


def test_strava_webhook_verify_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_VERIFY_TOKEN", "secret-token")
    with TestClient(app) as client:
        res = client.get(
            "/v1/sync/strava/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "xyz"},
        )
    assert res.status_code == 403
