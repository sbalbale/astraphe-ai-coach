"""
Live progress for a coach reply that is being generated in the background.

POST /v1/coach/message/async returns before the reply exists and the client polls for
it. While the agentic loop runs it reports "thinking" / "tool" steps; this module keeps
those steps per athlete + conversation so GET /conversations/{id}/progress can show
what the coach is doing instead of a generic spinner.

Uses Redis when REDIS_URL is set (the API runs several replicas, and a poll can land on
a different one than the worker), else an in-process dict. Entries expire after
PROGRESS_TTL_SEC; everything is best-effort and never raises into the caller.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

PROGRESS_TTL_SEC = 600
MAX_EVENTS = 60

# key -> (expires_at_monotonic, events)
_memory: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _key(athlete_id: str, conversation_id: str) -> str:
    return f"coach:progress:{athlete_id}:{conversation_id}"


def _memory_prune(now: float) -> None:
    for k in [k for k, (exp, _) in _memory.items() if exp <= now]:
        _memory.pop(k, None)


async def reset(athlete_id: str, conversation_id: str) -> None:
    """Start a fresh progress log for a new reply."""
    key = _key(athlete_id, conversation_id)
    redis = get_redis()
    if redis is not None:
        try:
            await redis.delete(key)
            return
        except Exception as exc:  # fall back to memory
            logger.warning("coach_progress reset via redis failed: %s", exc)
    _memory.pop(key, None)


async def append(athlete_id: str, conversation_id: str, event: dict[str, Any]) -> None:
    """Record one progress event ({"status": ..., "tool"?: ...})."""
    entry = {**event, "at": time.time()}
    key = _key(athlete_id, conversation_id)
    redis = get_redis()
    if redis is not None:
        try:
            await redis.rpush(key, json.dumps(entry, default=str))
            await redis.ltrim(key, -MAX_EVENTS, -1)
            await redis.expire(key, PROGRESS_TTL_SEC)
            return
        except Exception as exc:
            logger.warning("coach_progress append via redis failed: %s", exc)
    now = time.monotonic()
    _memory_prune(now)
    _, events = _memory.get(key, (0.0, []))
    events = (events + [entry])[-MAX_EVENTS:]
    _memory[key] = (now + PROGRESS_TTL_SEC, events)


async def read(athlete_id: str, conversation_id: str) -> list[dict[str, Any]]:
    """Progress events for the reply in flight, oldest first (empty when none)."""
    key = _key(athlete_id, conversation_id)
    redis = get_redis()
    if redis is not None:
        try:
            raw = await redis.lrange(key, 0, -1)
            out: list[dict[str, Any]] = []
            for item in raw or []:
                try:
                    out.append(json.loads(item))
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as exc:
            logger.warning("coach_progress read via redis failed: %s", exc)
    now = time.monotonic()
    _memory_prune(now)
    return list(_memory.get(key, (0.0, []))[1])
