from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.config import settings
from app.core import supabase_health


def _run_async(coro):
    return asyncio.run(coro)


def test_ping_supabase_false_without_url(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "key")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "key")

    assert _run_async(supabase_health.ping_supabase()) is False


def test_ping_supabase_false_without_any_key(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")

    assert _run_async(supabase_health.ping_supabase()) is False


def test_ping_supabase_true_when_probe_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "anon-key")

    with patch.object(supabase_health, "_probe_postgrest_sync", return_value=None):
        assert _run_async(supabase_health.ping_supabase()) is True


def test_ping_supabase_false_when_probe_raises(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "anon-key")

    with patch.object(supabase_health, "_probe_postgrest_sync", side_effect=RuntimeError("down")):
        assert _run_async(supabase_health.ping_supabase()) is False


def test_probe_postgrest_sync_queries_athletes_table():
    fake_query = MagicMock()
    fake_db = MagicMock()
    fake_db.table.return_value = fake_query
    fake_query.select.return_value = fake_query
    fake_query.limit.return_value = fake_query

    with patch.object(supabase_health, "get_admin_db", return_value=fake_db):
        supabase_health._probe_postgrest_sync()

    fake_db.table.assert_called_once_with("athletes")
    fake_query.select.assert_called_once_with("id")
    fake_query.limit.assert_called_once_with(1)
    fake_query.execute.assert_called_once()
