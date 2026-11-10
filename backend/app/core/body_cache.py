"""
Redis cache for the Body screens' payloads (GET /v1/biometrics/heart-rate, GET /v1/weight).

Keys are ``body:{athlete_id}:v{N}:{name}`` where N is ``body_version:{athlete_id}``;
bumping it (any change to the athlete's workouts, weigh-ins, heart rate series or
profile) retires every cached payload at once, as ``zones_version:`` does for
``detail:{athlete}:v{N}:{workout}``. Prod Redis runs with no maxmemory and
``noeviction``, so every payload key has a TTL (the version counters are a few bytes
each, like zones_version). TTLs are also the backstop for a writer that doesn't bump:
short for today (fills in through the day), longer for past days. Without Redis (local
dev) every call is a miss, and failures never raise.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

HR_TODAY_TTL = 60
HR_PAST_DAY_TTL = 30 * 60
WEIGHT_TTL = 10 * 60


def _version_key(athlete_id: str) -> str:
    return f"body_version:{athlete_id}"


async def _version(r: Any, athlete_id: str) -> str:
    v = await r.get(_version_key(athlete_id))
    if isinstance(v, bytes):
        v = v.decode()
    return f"v{int(v or 0)}"


async def get_cached(athlete_id: str, name: str) -> dict | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(f"body:{athlete_id}:{await _version(r, athlete_id)}:{name}")
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        logger.debug("body cache get failed athlete=%s %s: %s", athlete_id, name, e)
        return None


async def set_cached(athlete_id: str, name: str, payload: dict, ttl: int) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        key = f"body:{athlete_id}:{await _version(r, athlete_id)}:{name}"
        await r.setex(key, ttl, json.dumps(payload, default=str))
    except Exception as e:  # noqa: BLE001
        logger.debug("body cache set failed athlete=%s %s: %s", athlete_id, name, e)


async def bump_body_cache(athlete_id: str) -> None:
    """Retire every cached Body payload for the athlete. Never raises."""
    r = get_redis()
    if r is None:
        return
    try:
        await r.incr(_version_key(athlete_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("body cache bump failed athlete=%s: %s", athlete_id, e)
