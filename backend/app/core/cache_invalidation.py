"""Clear the per-athlete read caches after their data changes."""

from __future__ import annotations

import logging

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def invalidate_athlete_caches(
    athlete_id: str, *, workouts: bool = False, profile: bool = False
) -> None:
    """
    Drop cached views of an athlete's data:
    - always: ``state:`` (CTL/ATL/readiness card) and this process's coach context;
    - ``profile=True``: ``profile:``;
    - ``workouts=True``: bump ``zones_version:``, which retires every cached
      ``detail:`` / ``zones:workout:`` entry for the athlete.

    Never raises: a cache that can't be cleared just expires on its TTL.
    """
    try:
        from app.services.ai_coach import invalidate_context_cache

        invalidate_context_cache(athlete_id)
    except Exception:  # noqa: BLE001
        pass
    r = get_redis()
    if r is None:
        return
    keys = [f"state:{athlete_id}"]
    if profile:
        keys.append(f"profile:{athlete_id}")
    try:
        await r.delete(*keys)
        if workouts:
            await r.incr(f"zones_version:{athlete_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning("cache invalidation failed for athlete_id=%s: %s", athlete_id, e)
