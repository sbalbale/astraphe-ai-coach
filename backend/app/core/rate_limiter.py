"""
Sliding-window rate limiter.

When REDIS_URL is configured:
  Uses Redis sorted sets + an atomic Lua script. Correct across multiple
  backend instances (Cloud Run scale-out, multiple workers).

When Redis is unavailable or not configured:
  Falls back to an in-process dict. Suitable for single-instance deployments
  and local development. State is lost on restart.
"""

import asyncio
import logging
import os
from collections import defaultdict
from time import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Atomic Lua sliding window.
# - Removes entries older than `window` seconds.
# - If count < limit, adds the new entry and returns 1 (allowed).
# - Otherwise returns 0 (denied) without adding.
_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('zremrangebyscore', key, '-inf', now - window)
local count = redis.call('zcard', key)
if count < limit then
    redis.call('zadd', key, now, member)
    redis.call('expire', key, window + 1)
    return 1
end
return 0
"""


class RateLimiter:
    """
    Drop-in replacement for the previous in-memory RateLimiter.
    Uses Redis when available; falls back to in-process state otherwise.
    """

    def __init__(self) -> None:
        self._memory: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        from app.core.redis import get_redis

        redis = get_redis()
        if redis is not None:
            try:
                return await self._redis_check(redis, key, limit, window_seconds)
            except Exception as exc:
                logger.warning("Redis rate-limit check failed, using memory: %s", exc)
        return await self._memory_check(key, limit, window_seconds)

    async def require(self, key: str, limit: int, window_seconds: int, detail: str) -> None:
        if not await self.check(key, limit, window_seconds):
            raise HTTPException(status_code=429, detail=detail)

    async def _redis_check(self, redis, key: str, limit: int, window_seconds: int) -> bool:
        now = time()
        member = f"{now:.6f}:{os.urandom(3).hex()}"
        result = await redis.eval(
            _LUA,
            1,
            f"rl:{key}",
            now,
            window_seconds,
            limit,
            member,
        )
        return bool(result)

    async def _memory_check(self, key: str, limit: int, window_seconds: int) -> bool:
        async with self._lock:
            now = time()
            cutoff = now - window_seconds
            self._memory[key] = [t for t in self._memory[key] if t > cutoff]
            if len(self._memory[key]) >= limit:
                return False
            self._memory[key].append(now)
            return True
