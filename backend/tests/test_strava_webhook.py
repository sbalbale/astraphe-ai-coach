"""Tests for Strava webhook handling and startup backfill orchestration."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_admin_db
from app.main import app

WEBHOOK_URL = "/v1/sync/strava/webhook"


class _OAuthTokenQuery:
    def __init__(self, row: dict | None):
        self._row = row

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self._row)


class _FakeAdminDb:
    def __init__(self, oauth_row: dict | None):
        self._oauth_row = oauth_row

    def table(self, name: str):
        if name == "oauth_tokens":
            return _OAuthTokenQuery(self._oauth_row)
        raise AssertionError(f"unexpected table {name}")


def _client_with_db(oauth_row: dict | None) -> TestClient:
    app.dependency_overrides[get_admin_db] = lambda: _FakeAdminDb(oauth_row)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_admin_db, None)


def test_strava_webhook_invalid_json_returns_200(capsys):
    with _client_with_db(None) as client:
        resp = client.post(
            WEBHOOK_URL,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert "[strava.webhook] invalid JSON — dropping" in capsys.readouterr().out


def test_strava_webhook_missing_owner_id_returns_200(capsys):
    payload = {
        "aspect_type": "create",
        "object_type": "activity",
        "object_id": 123,
    }
    with _client_with_db(None) as client:
        resp = client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200
    out = capsys.readouterr().out
    assert "[strava.webhook] missing owner_id — dropping" in out


def test_strava_webhook_unknown_owner_returns_200(capsys):
    payload = {
        "aspect_type": "create",
        "object_type": "activity",
        "object_id": 123,
        "owner_id": 99999,
    }
    with _client_with_db(None) as client:
        resp = client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200
    out = capsys.readouterr().out
    assert "[strava.webhook] unknown owner strava_id=99999 — dropping" in out


def test_strava_webhook_queues_ingest_for_known_owner():
    payload = {
        "aspect_type": "create",
        "object_type": "activity",
        "object_id": 456,
        "owner_id": 111,
    }
    oauth_row = {"athlete_id": "athlete-uuid-1"}
    with patch(
        "app.routers.sync.strava_service.ingest_strava_activity",
        new_callable=AsyncMock,
    ) as mock_ingest:
        with _client_with_db(oauth_row) as client:
            resp = client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200
    # BackgroundTasks run synchronously in Starlette TestClient
    mock_ingest.assert_called_once()
    args, kwargs = mock_ingest.call_args
    assert args[0] == 111
    assert args[1] == 456
    assert kwargs["athlete_id"] == "athlete-uuid-1"


def test_backfill_recent_iterates_strava_athletes():
    from app.services import strava as strava_service

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(
            data=[
                {"athlete_id": "a1", "external_user_id": "100"},
                {"athlete_id": "a2", "external_user_id": "bad-id"},
            ]
        )
    )

    async def _run():
        with (
            patch("app.dependencies.get_admin_db", return_value=mock_db),
            patch(
                "app.services.strava.get_valid_token",
                new_callable=AsyncMock,
                side_effect=["token-a1"],
            ),
            patch(
                "app.services.strava.backfill_historical_data",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_bf,
        ):
            await strava_service.backfill_recent(hours=6)

        assert mock_bf.await_count == 1
        mock_bf.assert_awaited_once_with(
            "a1", 100, "token-a1", mock_db, hours=6
        )

    asyncio.run(_run())
