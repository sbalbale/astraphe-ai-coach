"""Unit tests for astraphe_mcp.db — athlete_id resolution and its cache."""
from __future__ import annotations

import pytest

from astraphe_mcp.db import AthleteProfileNotFound, resolve_athlete_id


@pytest.mark.asyncio
async def test_resolve_athlete_id_found(fake_db, mock_athlete_id):
    athlete_id = await resolve_athlete_id(fake_db, "some-token")
    assert athlete_id == mock_athlete_id


@pytest.mark.asyncio
async def test_resolve_athlete_id_not_found(fake_db):
    fake_db._table_seeds["athletes"] = []
    with pytest.raises(AthleteProfileNotFound):
        await resolve_athlete_id(fake_db, "some-token")


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
    first = await resolve_athlete_id(fake_db, token)
    second = await resolve_athlete_id(fake_db, token)

    assert first == second == mock_athlete_id
    assert call_count == 1, "second call within the cache TTL should not hit the DB again"
