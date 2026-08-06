from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.core import redis as redis_module


def _run_async(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_redis_singleton():
    """Each test gets a clean module-level client singleton."""
    redis_module._client = None
    yield
    redis_module._client = None


def test_describe_redis_url_unset():
    assert redis_module.describe_redis_url(None) == "unset"
    assert redis_module.describe_redis_url("") == "unset"


def test_describe_redis_url_strips_credentials_and_path():
    url = "rediss://default:supersecret@my-host.upstash.io:6380/0?foo=bar"

    result = redis_module.describe_redis_url(url)

    assert "supersecret" not in result
    assert result.startswith("rediss://my-host.upstash.io:6380")


def test_get_redis_returns_none_when_url_unset(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", None)

    assert redis_module.get_redis() is None


def test_get_redis_creates_client_when_url_set(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379")
    fake_client = MagicMock()

    with patch("redis.asyncio.Redis.from_url", return_value=fake_client) as mock_from_url:
        client = redis_module.get_redis()

    mock_from_url.assert_called_once()
    assert client is fake_client
    # Second call reuses the cached singleton rather than reconnecting.
    with patch("redis.asyncio.Redis.from_url") as mock_from_url_2:
        assert redis_module.get_redis() is fake_client
        mock_from_url_2.assert_not_called()


def test_get_redis_returns_none_when_construction_fails(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379")

    with patch("redis.asyncio.Redis.from_url", side_effect=RuntimeError("boom")):
        assert redis_module.get_redis() is None


def test_close_redis_clears_singleton():
    fake_client = MagicMock()
    fake_client.aclose = AsyncMock()
    redis_module._client = fake_client

    _run_async(redis_module.close_redis())

    fake_client.aclose.assert_awaited_once()
    assert redis_module._client is None


def test_close_redis_noop_when_no_client():
    redis_module._client = None

    _run_async(redis_module.close_redis())  # should not raise

    assert redis_module._client is None


def test_ping_redis_false_when_no_client(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", None)

    assert _run_async(redis_module.ping_redis()) is False


def test_ping_redis_true_when_client_responds(monkeypatch):
    fake_client = MagicMock()
    fake_client.ping = AsyncMock(return_value=True)
    redis_module._client = fake_client

    assert _run_async(redis_module.ping_redis()) is True


def test_ping_redis_false_when_ping_raises(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379")
    fake_client = MagicMock()
    fake_client.ping = AsyncMock(side_effect=RuntimeError("down"))
    redis_module._client = fake_client

    assert _run_async(redis_module.ping_redis()) is False
