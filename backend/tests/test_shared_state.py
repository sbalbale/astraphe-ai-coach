"""State shared by the API replicas through Redis (quotas, locks, cache versions)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core import redis as redis_mod


class _SyncRedis:
    """Enough of redis.Redis: strings with expiry metadata and INCR."""

    def __init__(self):
        self.data, self.exat, self.expire_s = {}, {}, {}

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v, exat=None, **_):
        self.data[k] = v
        if exat:
            self.exat[k] = exat

    def setex(self, k, ttl, v):
        self.data[k], self.expire_s[k] = v, ttl

    def exists(self, k):
        return int(k in self.data)

    def incr(self, k):
        self.data[k] = str(int(self.data.get(k) or 0) + 1)
        return int(self.data[k])

    def expire(self, k, s):
        self.expire_s[k] = s

    def pipeline(self):
        r = self

        class P:
            def __init__(self):
                self.ops = []

            def incr(self, k):
                self.ops.append(lambda: r.incr(k))

            def expire(self, k, s):
                self.ops.append(lambda: r.expire(k, s))

            def execute(self):
                return [op() for op in self.ops]

        return P()


# ---- #2 Gemini RPM shared across replicas ----------------------------------------


def test_gemini_slot_uses_the_shared_window():
    from app.services import gemini_quota as q

    r = MagicMock()
    r.eval.side_effect = [[1, 0], [0, 4200]]
    with patch.object(redis_mod, "get_sync_redis", return_value=r):
        assert q._take_slot("gemma-4-31b-it", 27) is None
        assert q._take_slot("gemma-4-31b-it", 27) == 4.2
    key = r.eval.call_args.args[2]
    assert key == "gemini_rpm:gemma-4-31b-it"


def test_gemini_slot_falls_back_to_process_count_when_redis_fails():
    from app.services import gemini_quota as q

    r = MagicMock()
    r.eval.side_effect = ConnectionError("down")
    q._call_times.pop("m-x", None)
    with patch.object(redis_mod, "get_sync_redis", return_value=r):
        assert q._take_slot("m-x", 1) is None
        assert q._take_slot("m-x", 1) > 0  # second call: window full in-process


# ---- #2 plan import quotas -----------------------------------------------------------


def test_plan_import_limits_are_shared():
    from app.services import plan_import as pi

    r = _SyncRedis()
    now = datetime(2026, 11, 9, 20, tzinfo=timezone.utc)
    with patch.object(redis_mod, "get_sync_redis", return_value=r):
        assert pi._is_exhausted("gemini-3.8-flash", now) is False
        pi._mark_exhausted("gemini-3.8-flash", now)
        assert pi._is_exhausted("gemini-3.8-flash", now) is True
        assert r.exat["plan_import_exhausted:gemini-3.8-flash"] == int(pi._next_pacific_midnight(now).timestamp())
        left = pi._athlete_quota_left("a1", "2026-11-09")
        pi._count_athlete_import("a1", "2026-11-09")
        # another replica (empty process memory) sees the same count
        pi._athlete_imports.clear()
        assert pi._athlete_quota_left("a1", "2026-11-09") == left - 1
    assert r.expire_s["plan_imports:a1:2026-11-09"] == 2 * 86400


# ---- #3 regeneration lock -------------------------------------------------------------


def test_regen_lock_is_exclusive_across_replicas_and_released_by_owner():
    from app.routers import analysis

    store: dict[str, str] = {}

    class _AsyncRedis:
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in store:
                return None
            store[k] = v
            return True

        async def eval(self, script, n, k, token):
            if store.get(k) == token:
                del store[k]
                return 1
            return 0

    r = _AsyncRedis()
    with patch.object(redis_mod, "get_redis", return_value=r):
        assert asyncio.run(analysis._claim_regen("a1:day")) is True
        # the other replica: its own process set is empty, Redis says taken
        analysis._regen_in_flight.clear()
        token = analysis._regen_tokens.pop("a1:day")
        assert asyncio.run(analysis._claim_regen("a1:day")) is False
        analysis._regen_tokens["a1:day"] = token
        asyncio.run(analysis._release_regen("a1:day"))
        assert "regen:a1:day" not in store
        assert asyncio.run(analysis._claim_regen("a1:day")) is True
        asyncio.run(analysis._release_regen("a1:day"))


# ---- #5 start-up lists ----------------------------------------------------------------


def test_workouts_first_page_is_cached_older_pages_are_not():
    from app.routers import workouts as wr

    r = _SyncRedis()
    q = MagicMock()
    q.select.return_value = q
    q.eq.return_value = q
    q.lt.return_value = q
    q.order.return_value = q
    q.limit.return_value = q
    q.execute.return_value = SimpleNamespace(data=[{"id": "w1", "duration_seconds": 60}])
    db = SimpleNamespace(table=lambda name: q)
    with patch.object(redis_mod, "get_sync_redis", return_value=r):
        first = wr.get_workouts(limit=200, before=None, athlete_id="a1", db=db)
        again = wr.get_workouts(limit=200, before=None, athlete_id="a1", db=db)
        wr.get_workouts(limit=200, before=datetime(2026, 1, 1), athlete_id="a1", db=db)
    assert first == again == [{"id": "w1", "duration_seconds": 60, "duration_secs": 60}]
    assert q.execute.call_count == 2  # the repeat came from Redis; the older page didn't cache
    assert r.expire_s["body:a1:v0:workouts:200"] > 0


def test_processing_writers_bump_the_version():
    from app.core import body_cache
    from app.services import processing

    with patch.object(body_cache, "bump_body_cache_sync") as bump, patch.object(
        processing, "_process_and_save_biometrics", return_value="ok"
    ):
        assert processing.process_and_save_biometrics(MagicMock(), "a1", MagicMock()) == "ok"
    bump.assert_called_once_with("a1")


# ---- #6 coach context ------------------------------------------------------------------


def test_coach_context_rebuilds_when_another_replica_changed_data():
    from app.services import ai_coach

    r = _SyncRedis()
    calls = {"n": 0}

    def summary(*a, **k):
        calls["n"] += 1
        return {"n": calls["n"]}

    ai_coach._context_parts_cache.pop("a1", None)
    with patch.object(redis_mod, "get_sync_redis", return_value=r), patch.object(
        ai_coach, "_summarize_biometrics", side_effect=summary
    ), patch.object(ai_coach, "_summarize_athlete_profile", return_value={}), patch.object(
        ai_coach, "_summarize_training_load", return_value={}
    ):
        first = ai_coach._get_context_parts_cached(None, "a1")
        assert ai_coach._get_context_parts_cached(None, "a1") == first  # cached
        r.incr("body_version:a1")  # a write on the other replica
        assert ai_coach._get_context_parts_cached(None, "a1")[0] == {"n": 2}
    ai_coach._context_parts_cache.pop("a1", None)
