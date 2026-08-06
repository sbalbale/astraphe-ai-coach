from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import settings
from app.services import strava_webhook_sub as sub


def test_expected_callback_url_returns_none_without_app_base_url(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "")

    assert sub.expected_callback_url() is None


def test_expected_callback_url_joins_base_and_prefix(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://api.astrapheai.com/")
    monkeypatch.setattr(settings, "API_PREFIX", "/v1")

    assert (
        sub.expected_callback_url()
        == "https://api.astrapheai.com/v1/sync/strava/webhook"
    )


def test_fetch_push_subscriptions_returns_empty_without_client_credentials(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "")
    monkeypatch.setattr(settings, "STRAVA_CLIENT_SECRET", "")

    assert sub.fetch_push_subscriptions() == []


def test_fetch_push_subscriptions_returns_list_from_strava(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "STRAVA_CLIENT_SECRET", "client-secret")

    fake_response = MagicMock()
    fake_response.json.return_value = [{"id": 1, "callback_url": "https://x/hook"}]
    fake_response.raise_for_status.return_value = None

    with patch.object(sub.httpx, "get", return_value=fake_response) as mock_get:
        result = sub.fetch_push_subscriptions()

    mock_get.assert_called_once()
    assert result == [{"id": 1, "callback_url": "https://x/hook"}]


def test_fetch_push_subscriptions_returns_empty_when_payload_not_list(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "STRAVA_CLIENT_SECRET", "client-secret")

    fake_response = MagicMock()
    fake_response.json.return_value = {"unexpected": "shape"}
    fake_response.raise_for_status.return_value = None

    with patch.object(sub.httpx, "get", return_value=fake_response):
        assert sub.fetch_push_subscriptions() == []


def test_subscription_matches_app_base_skips_when_no_expected_url(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "")

    ok, detail = sub.subscription_matches_app_base()

    assert ok is True
    assert "APP_BASE_URL not set" in detail


def test_subscription_matches_app_base_reports_query_failure(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://api.astrapheai.com")
    monkeypatch.setattr(sub, "fetch_push_subscriptions", MagicMock(side_effect=RuntimeError("boom")))

    ok, detail = sub.subscription_matches_app_base()

    assert ok is True
    assert "Could not query Strava subscriptions" in detail


def test_subscription_matches_app_base_reports_no_subscriptions(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://api.astrapheai.com")
    monkeypatch.setattr(settings, "API_PREFIX", "/v1")
    monkeypatch.setattr(sub, "fetch_push_subscriptions", MagicMock(return_value=[]))

    ok, detail = sub.subscription_matches_app_base()

    assert ok is False
    assert "No Strava push subscription" in detail


def test_subscription_matches_app_base_reports_match():
    expected = sub.expected_callback_url()

    def _fake_fetch():
        return [{"id": 42, "callback_url": expected}]

    with patch.object(sub, "fetch_push_subscriptions", _fake_fetch):
        ok, detail = sub.subscription_matches_app_base()

    assert ok is True
    assert "Strava webhook OK (id=42)" in detail


def test_subscription_matches_app_base_reports_mismatch():
    def _fake_fetch():
        return [{"id": 7, "callback_url": "https://other/hook"}]

    with patch.object(sub, "fetch_push_subscriptions", _fake_fetch):
        ok, detail = sub.subscription_matches_app_base()

    assert ok is False
    assert "Strava webhook mismatch" in detail
    assert "7→https://other/hook" in detail
