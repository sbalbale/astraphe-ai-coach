"""
Async Redis client singleton.

Returns None (and logs a warning) when REDIS_URL is not configured, so all
callers can degrade gracefully rather than crashing.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None


def get_redis():
    """
    Returns the redis.asyncio.Redis client, or None if REDIS_URL is not set.
    The client is created lazily; no network connection is made until the
    first command is issued.
    """
    global _client
    if _client is None:
        from app.config import settings

        if not settings.REDIS_URL:
            return None
        try:
            from redis.asyncio import Redis

            _client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            logger.info("Redis client initialised (%s)", settings.REDIS_URL.split("@")[-1])
        except Exception as exc:
            logger.warning("Redis client init failed: %s", exc)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping_redis() -> bool:
    """Health-check helper. Returns True if Redis is reachable."""
    r = get_redis()
    if r is None:
        return False
    try:
        return await r.ping()
    except Exception:
        return False
