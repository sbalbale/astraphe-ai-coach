# Redis — AI Context

## Purpose

Redis backs the two rate limiters. There is no other Redis usage today, but the client is available for caching or queuing if needed.

## Client (`backend/app/core/redis.py`)

- `get_redis()` — returns `redis.asyncio.Redis` or `None`
  - Lazy: creates client on first call, no connection until first command
  - Returns `None` if `settings.REDIS_URL` is falsy (unset/empty)
  - Safe to call from anywhere; never raises
- `close_redis()` — async, called on FastAPI shutdown event
- `ping_redis()` — async bool, used by `/health`

## Rate limiter (`backend/app/core/rate_limiter.py`)

`RateLimiter` class — used as a singleton in both `dependencies.py` and `main.py`.

### Redis path (when `get_redis()` returns a client)
Sliding window via Lua script (atomic):
- Key: `rl:{key}` (ZSET, scores are float timestamps)
- On each call: removes entries older than `window_seconds`, counts remaining, adds new entry if count < limit
- Member uniqueness: `"{timestamp:.6f}:{3_random_bytes_hex}"` prevents collisions
- Returns 1 (allowed) or 0 (denied)

### Memory fallback (when Redis unavailable)
- `defaultdict(list[float])` per key, pruned on each check
- `asyncio.Lock` for thread safety within a single process
- Does NOT share state across instances

### Error handling
If a Redis command raises, logs a warning and falls back to in-memory for that request. Does not break the request.

## Instances

Two singletons exist:
1. `_rate_limiter` in `dependencies.py` — per-user AI rate limits (rpm/rph from tier config)
2. `_ip_rate_limiter` in `main.py` — per-IP limit (`settings.IP_RATE_LIMIT_RPM`, default 100/min) applied in `IPRateLimitMiddleware`

## Config

`settings.REDIS_URL: Optional[str]`
- Local: `redis://localhost:6379`
- Upstash: `rediss://default:<token>@<host>.upstash.io:6380`
- Unset → in-memory fallback

## Adding Redis to a new feature

```python
from app.core.redis import get_redis

async def my_handler():
    redis = get_redis()
    if redis is not None:
        await redis.set("key", "value", ex=300)
        val = await redis.get("key")
```

Always guard with `if redis is not None` so the feature degrades gracefully when Redis is unavailable.
