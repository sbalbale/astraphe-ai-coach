"""
Async Redis client singleton.

Returns None (and logs a warning) when REDIS_URL is not configured, so all
callers can degrade gracefully rather than crashing.
"""

import logging
from urllib.parse import urlsplit, urlunsplit
from typing import Optional

logger = logging.getLogger(__name__)

_client = None


def describe_redis_url(url: str | None) -> str:
    if not url:
        return "unset"
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host}{port}" if host else parsed.netloc.split("@")[-1]
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


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
            logger.info("Redis client initialised (%s)", describe_redis_url(settings.REDIS_URL))
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
    except Exception as exc:
        from app.config import settings

        logger.warning(
            "Redis ping failed for %s: %s",
            describe_redis_url(settings.REDIS_URL),
            exc,
        )
        return False
