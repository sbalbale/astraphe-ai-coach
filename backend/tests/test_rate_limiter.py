from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.core.rate_limiter import RateLimiter


def _run_async(coro):
    return asyncio.run(coro)


def test_memory_check_allows_up_to_limit_then_denies():
    limiter = RateLimiter()

    async def _run():
        results = [await limiter._memory_check("k", limit=2, window_seconds=60) for _ in range(3)]
        return results

    assert _run_async(_run()) == [True, True, False]


def test_memory_check_expires_old_entries(monkeypatch):
    limiter = RateLimiter()
    times = iter([1000.0, 1000.0, 1070.0])  # third call is 70s later, window=60s
    monkeypatch.setattr("app.core.rate_limiter.time", lambda: next(times))

    async def _run():
        first = await limiter._memory_check("k", limit=1, window_seconds=60)
        second = await limiter._memory_check("k", limit=1, window_seconds=60)  # same t, over limit
        third = await limiter._memory_check("k", limit=1, window_seconds=60)  # window elapsed
        return first, second, third

    assert _run_async(_run()) == (True, False, True)


def test_check_falls_back_to_memory_when_redis_unavailable(monkeypatch):
    limiter = RateLimiter()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: None)

    assert _run_async(limiter.check("k", limit=5, window_seconds=60)) is True


def test_check_uses_redis_when_available(monkeypatch):
    limiter = RateLimiter()

    class _FakeRedis:
        async def eval(self, *_a, **_k):
            return 1

    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis())

    assert _run_async(limiter.check("k", limit=5, window_seconds=60)) is True


def test_check_redis_denies_over_limit(monkeypatch):
    limiter = RateLimiter()

    class _FakeRedis:
        async def eval(self, *_a, **_k):
            return 0

    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FakeRedis())

    assert _run_async(limiter.check("k", limit=5, window_seconds=60)) is False


def test_check_falls_back_to_memory_when_redis_errors(monkeypatch):
    limiter = RateLimiter()

    class _FailingRedis:
        async def eval(self, *_a, **_k):
            raise RuntimeError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis", lambda: _FailingRedis())

    # Redis raised, but the in-process fallback still allows the first request.
    assert _run_async(limiter.check("k", limit=5, window_seconds=60)) is True


def test_require_raises_429_when_denied(monkeypatch):
    limiter = RateLimiter()
    monkeypatch.setattr(limiter, "check", lambda *a, **k: _immediate_false())

    async def _immediate_false():
        return False

    with pytest.raises(HTTPException) as exc_info:
        _run_async(limiter.require("k", limit=1, window_seconds=60, detail="too many"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "too many"


def test_require_passes_when_allowed(monkeypatch):
    limiter = RateLimiter()

    async def _immediate_true(*_a, **_k):
        return True

    monkeypatch.setattr(limiter, "check", _immediate_true)

    _run_async(limiter.require("k", limit=1, window_seconds=60, detail="too many"))  # no raise
