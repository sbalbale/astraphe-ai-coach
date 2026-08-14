"""Unit tests for astraphe_mcp.db — athlete_id resolution and its cache."""
from __future__ import annotations

import pytest

from astraphe_mcp.db import (
    AthleteProfileNotFound,
    _athlete_id_cache,
    _prune_expired_athlete_id_cache_entries,
    get_scoped_db,
    resolve_athlete_id,
)
from tests.conftest import FAKE_USER_ID


def test_get_scoped_db_applies_the_caller_token():
    # postgrest.auth(token) sets postgrest.headers (what's actually sent on each
    # request) — NOT postgrest.session.headers, which stays pinned to the anon key used
    # at client construction. Confirmed against the real supabase-py implementation, and
    # against a live local Supabase returning real athlete-scoped data end to end (see
    # docs/MCP_SERVER.md).
    db = get_scoped_db("some-access-token")
    assert db.postgrest.headers["Authorization"] == "Bearer some-access-token"


def test_get_scoped_db_falls_back_without_raising_if_auth_itself_raises(monkeypatch):
    """If postgrest.auth() itself isn't usable for some reason, this must degrade to a
    best-effort header update rather than raising out of get_scoped_db — same defensive
    shape as backend/app/dependencies.py's _with_auth_token()."""
    from astraphe_mcp import db as db_module
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.postgrest.auth.side_effect = RuntimeError("auth() unavailable on this client")

    monkeypatch.setattr(db_module, "create_client", lambda *a, **k: fake_client)
    db = get_scoped_db("some-access-token")  # must not raise
    fake_client.postgrest.session.headers.update.assert_called_once_with(
        {"Authorization": "Bearer some-access-token"}
    )


def test_prune_expired_athlete_id_cache_entries_removes_only_expired():
    _athlete_id_cache.clear()
    _athlete_id_cache["expired-token"] = ("athlete-1", 0.0)
    _athlete_id_cache["fresh-token"] = ("athlete-2", 1_000_000.0)

    _prune_expired_athlete_id_cache_entries(now=1_000_000.0)

    assert "expired-token" not in _athlete_id_cache
    assert "fresh-token" in _athlete_id_cache
    _athlete_id_cache.clear()


@pytest.mark.asyncio
async def test_resolve_athlete_id_found(fake_db, mock_athlete_id):
    athlete_id = await resolve_athlete_id(fake_db, "some-token", FAKE_USER_ID)
    assert athlete_id == mock_athlete_id


@pytest.mark.asyncio
async def test_resolve_athlete_id_not_found(fake_db):
    fake_db._table_seeds["athletes"] = []
    with pytest.raises(AthleteProfileNotFound):
        await resolve_athlete_id(fake_db, "some-token", FAKE_USER_ID)


@pytest.mark.asyncio
async def test_resolve_athlete_id_is_cached(fake_db, mock_athlete_id, monkeypatch):
    call_count = 0
    original_table = fake_db.table

    def counting_table(name):
        nonlocal call_count
        if name == "athletes":
            call_count += 1
        return original_table(name)

    monkeypatch.setattr(fake_db, "table", counting_table)

    token = "cache-me-token"
    first = await resolve_athlete_id(fake_db, token, FAKE_USER_ID)
    second = await resolve_athlete_id(fake_db, token, FAKE_USER_ID)

    assert first == second == mock_athlete_id
    assert call_count == 1, "second call within the cache TTL should not hit the DB again"


@pytest.mark.asyncio
async def test_resolve_athlete_id_does_not_call_auth_get_user(fake_db):
    """user_id must come from the already-verified token (AccessToken.subject), not a
    second auth.get_user() round trip — regression test for that redundant call."""
    await resolve_athlete_id(fake_db, "some-token", FAKE_USER_ID)
    fake_db.auth.get_user.assert_not_called()
