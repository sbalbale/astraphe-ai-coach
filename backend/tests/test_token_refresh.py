from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import token_refresh


def _run_async(coro):
    return asyncio.run(coro)


def test_token_expires_at_computes_iso_timestamp():
    result = token_refresh.token_expires_at({"expires_in": 3600})

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed > datetime.now(timezone.utc)


def test_token_expires_at_returns_none_for_missing_or_invalid():
    assert token_refresh.token_expires_at({}) is None
    assert token_refresh.token_expires_at({"expires_in": "not-a-number"}) is None
    assert token_refresh.token_expires_at({"expires_in": None}) is None


class _RefreshQuery:
    def __init__(self, rows):
        self._rows = rows
        self.updated: dict | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def update(self, payload):
        self.updated = payload
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _RefreshDb:
    def __init__(self, rows):
        self.query = _RefreshQuery(rows)

    def table(self, name):
        assert name == "oauth_tokens"
        return self.query


def test_refresh_expiring_whoop_tokens_noop_when_no_rows():
    db = _RefreshDb(rows=[])

    with patch.object(token_refresh, "get_admin_db", return_value=db):
        _run_async(token_refresh._refresh_expiring_whoop_tokens())

    assert db.query.updated is None


def test_refresh_expiring_whoop_tokens_updates_row_on_success():
    rows = [
        {
            "id": "row-1",
            "athlete_id": "athlete-1",
            "external_user_id": "ext-1",
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": "2026-01-01T00:00:00Z",
        }
    ]
    db = _RefreshDb(rows=rows)

    fake_refresh = AsyncMock(
        return_value={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}
    )

    with patch.object(token_refresh, "get_admin_db", return_value=db), patch.object(
        token_refresh.whoop, "refresh_oauth_token", fake_refresh
    ):
        _run_async(token_refresh._refresh_expiring_whoop_tokens())

    fake_refresh.assert_awaited_once_with("old-refresh")
    assert db.query.updated["access_token"] == "new-access"
    assert db.query.updated["refresh_token"] == "new-refresh"
    assert "expires_at" in db.query.updated


def test_refresh_expiring_whoop_tokens_skips_row_without_new_access():
    rows = [
        {
            "id": "row-1",
            "athlete_id": "athlete-1",
            "refresh_token": "old-refresh",
        }
    ]
    db = _RefreshDb(rows=rows)
    fake_refresh = AsyncMock(return_value={})

    with patch.object(token_refresh, "get_admin_db", return_value=db), patch.object(
        token_refresh.whoop, "refresh_oauth_token", fake_refresh
    ):
        _run_async(token_refresh._refresh_expiring_whoop_tokens())

    assert db.query.updated is None


def test_refresh_expiring_whoop_tokens_swallows_per_row_errors():
    rows = [{"id": "row-1", "athlete_id": "athlete-1", "refresh_token": "bad"}]
    db = _RefreshDb(rows=rows)
    fake_refresh = AsyncMock(side_effect=RuntimeError("provider down"))

    with patch.object(token_refresh, "get_admin_db", return_value=db), patch.object(
        token_refresh.whoop, "refresh_oauth_token", fake_refresh
    ):
        _run_async(token_refresh._refresh_expiring_whoop_tokens())  # should not raise

    assert db.query.updated is None


def test_refresh_expiring_whoop_tokens_handles_query_failure():
    class _FailingDb:
        def table(self, _name):
            raise RuntimeError("db unavailable")

    with patch.object(token_refresh, "get_admin_db", return_value=_FailingDb()):
        _run_async(token_refresh._refresh_expiring_whoop_tokens())  # should not raise


def test_token_refresh_loop_runs_iteration_then_can_be_cancelled():
    call_count = {"n": 0}

    async def _fake_refresh():
        call_count["n"] += 1
        raise asyncio.CancelledError()

    async def _run():
        with patch.object(token_refresh, "_refresh_expiring_whoop_tokens", _fake_refresh):
            task = asyncio.ensure_future(token_refresh.token_refresh_loop())
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.CancelledError:
                pass

    _run_async(_run())
    assert call_count["n"] == 1
