from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.services import resend_service


def _run_async(coro):
    return asyncio.run(coro)


def test_sync_marketing_contact_noop_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "RESEND_AUDIENCE_ID", "audience-1")

    with patch.object(resend_service.httpx, "AsyncClient") as mock_client_cls:
        _run_async(resend_service.sync_marketing_contact("a@example.com", True))

    mock_client_cls.assert_not_called()


def test_sync_marketing_contact_noop_without_audience_id(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "key-1")
    monkeypatch.setattr(settings, "RESEND_AUDIENCE_ID", None)

    with patch.object(resend_service.httpx, "AsyncClient") as mock_client_cls:
        _run_async(resend_service.sync_marketing_contact("a@example.com", True))

    mock_client_cls.assert_not_called()


def test_sync_marketing_contact_posts_upsert_payload(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "key-1")
    monkeypatch.setattr(settings, "RESEND_AUDIENCE_ID", "audience-1")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    mock_ctx = MagicMock()
    mock_ctx.post = AsyncMock(return_value=mock_response)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(resend_service.httpx, "AsyncClient", mock_client_cls):
        _run_async(resend_service.sync_marketing_contact("a@example.com", subscribed=True))

    mock_ctx.post.assert_awaited_once()
    args, kwargs = mock_ctx.post.call_args
    assert args[0] == "https://api.resend.com/audiences/audience-1/contacts"
    assert kwargs["json"] == {"email": "a@example.com", "unsubscribed": False}
    assert kwargs["headers"]["Authorization"] == "Bearer key-1"


def test_sync_marketing_contact_swallows_http_errors(monkeypatch, capsys):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "key-1")
    monkeypatch.setattr(settings, "RESEND_AUDIENCE_ID", "audience-1")

    mock_ctx = MagicMock()
    mock_ctx.post = AsyncMock(side_effect=RuntimeError("network down"))

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(resend_service.httpx, "AsyncClient", mock_client_cls):
        # Should not raise despite the underlying request failing.
        _run_async(resend_service.sync_marketing_contact("a@example.com", subscribed=False))

    captured = capsys.readouterr()
    assert "Failed to sync contact" in captured.out
