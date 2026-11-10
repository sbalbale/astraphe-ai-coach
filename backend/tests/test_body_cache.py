from __future__ import annotations

import asyncio
import json
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import body_cache
from app.dependencies import get_current_athlete, get_user_db
from app.main import app


class _FakeRedis:
    """Async subset of redis.asyncio used by body_cache, recording TTLs."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, k):
        return self.data.get(k)

    async def setex(self, k, ttl, v):
        self.data[k], self.ttls[k] = v, ttl

    async def incr(self, k):
        self.data[k] = str(int(self.data.get(k) or 0) + 1)
        return int(self.data[k])


class _Down:
    async def get(self, k):
        raise ConnectionError("down")

    setex = incr = get


def _run(coro):
    return asyncio.run(coro)


def test_miss_set_hit_and_version_bump_retires():
    r = _FakeRedis()
    with patch.object(body_cache, "get_redis", return_value=r):
        assert _run(body_cache.get_cached("a1", "hrday:2026-11-08")) is None
        _run(body_cache.set_cached("a1", "hrday:2026-11-08", {"x": 1}, 60))
        assert "body:a1:v0:hrday:2026-11-08" in r.data  # same shape as detail:{a}:v{N}:{id}
        assert _run(body_cache.get_cached("a1", "hrday:2026-11-08")) == {"x": 1}
        _run(body_cache.bump_body_cache("a1"))
        assert _run(body_cache.get_cached("a1", "hrday:2026-11-08")) is None
        # another athlete is untouched by a1's bump
        _run(body_cache.set_cached("b2", "weight:2026-11-08", {"y": 2}, 60))
        _run(body_cache.bump_body_cache("a1"))
        assert _run(body_cache.get_cached("b2", "weight:2026-11-08")) == {"y": 2}
    # prod runs noeviction with no maxmemory: every payload key must expire
    assert all(k in r.ttls for k in r.data if k.startswith("body:"))


def test_no_redis_and_redis_down_are_plain_misses():
    with patch.object(body_cache, "get_redis", return_value=None):
        assert _run(body_cache.get_cached("a1", "x")) is None
        _run(body_cache.set_cached("a1", "x", {}, 60))
        _run(body_cache.bump_body_cache("a1"))
    with patch.object(body_cache, "get_redis", return_value=_Down()):
        assert _run(body_cache.get_cached("a1", "x")) is None
        _run(body_cache.set_cached("a1", "x", {}, 60))
        _run(body_cache.bump_body_cache("a1"))


def test_invalidate_athlete_caches_bumps_body_version():
    from app.core import cache_invalidation

    class _R(_FakeRedis):
        async def delete(self, *keys):
            for k in keys:
                self.data.pop(k, None)

    r = _R()
    with patch.object(cache_invalidation, "get_redis", return_value=r):
        _run(cache_invalidation.invalidate_athlete_caches("a1"))
    assert r.data["body_version:a1"] == "1"


def test_heart_rate_route_serves_cache_and_ttls_today_shorter():
    r = _FakeRedis()
    app.dependency_overrides[get_current_athlete] = lambda: "a1"
    app.dependency_overrides[get_user_db] = lambda: object()
    try:
        with patch.object(body_cache, "get_redis", return_value=r), patch(
            "app.services.time_utils.athlete_local_date", return_value=date(2026, 11, 9)
        ), patch("app.services.heart_rate_series.build_heart_rate_day", return_value={"date": "d"}) as build:
            with TestClient(app) as c:
                assert c.get("/v1/biometrics/heart-rate?date=2026-11-08").json() == {"date": "d"}
                assert c.get("/v1/biometrics/heart-rate?date=2026-11-08").json() == {"date": "d"}
                c.get("/v1/biometrics/heart-rate")  # today
    finally:
        app.dependency_overrides = {}
    assert build.call_count == 2  # the repeat of 2026-11-08 came from Redis
    assert r.ttls["body:a1:v0:hrday:2026-11-08"] == body_cache.HR_PAST_DAY_TTL
    assert r.ttls["body:a1:v0:hrday:2026-11-09"] == body_cache.HR_TODAY_TTL
    assert json.loads(r.data["body:a1:v0:hrday:2026-11-09"]) == {"date": "d"}
