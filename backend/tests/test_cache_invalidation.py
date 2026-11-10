import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import cache_invalidation
from app.services import ai_coach


def test_invalidate_clears_state_profile_and_bumps_zones_version():
    r = MagicMock()
    r.delete = AsyncMock()
    r.incr = AsyncMock()
    ai_coach._context_parts_cache["a1"] = ({}, {}, {}, 9e18)
    with patch.object(cache_invalidation, "get_redis", return_value=r):
        asyncio.run(cache_invalidation.invalidate_athlete_caches("a1", workouts=True, profile=True))
    r.delete.assert_awaited_once_with("state:a1", "profile:a1")
    assert [c.args for c in r.incr.await_args_list] == [("zones_version:a1",), ("body_version:a1",)]
    assert "a1" not in ai_coach._context_parts_cache


def test_invalidate_never_raises_when_redis_fails():
    r = MagicMock()
    r.delete = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(cache_invalidation, "get_redis", return_value=r):
        asyncio.run(cache_invalidation.invalidate_athlete_caches("a1"))


def test_invalidate_without_redis_is_a_noop():
    with patch.object(cache_invalidation, "get_redis", return_value=None):
        asyncio.run(cache_invalidation.invalidate_athlete_caches("a1", workouts=True))
