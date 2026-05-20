# Redis Rate Limiter — Implementation Plan
**Date:** 2026-05-19  
**Context:** The current in-memory `RateLimiter` in `backend/app/dependencies.py` works correctly for a single Cloud Run container but loses all state on each new instance. Under horizontal scaling, a user can multiply their effective rate limit by the number of running containers.

---

## Why This Matters

Cloud Run scales automatically. A sudden traffic spike spins up additional containers within seconds. At that point:

- Each container tracks its own per-user window in `self._windows` (a plain Python dict).
- A user making 40 AI requests/minute across 3 containers would send 120 requests/minute without triggering a limit.
- The AI endpoints are the most expensive part of the stack (Gemini token costs + Gemini quota consumption).

---

## Recommended Solution: Upstash Redis

[Upstash](https://upstash.com) is a serverless Redis that bills per request, has no idle cost, and has a Python SDK that works from Cloud Run without managing connection pools.

**Alternative:** A self-managed Redis instance on Cloud Memorystore (GCP) also works but adds infrastructure complexity and a persistent monthly cost.

### Why Upstash over Cloud Memorystore

| Criteria | Upstash | Cloud Memorystore |
|---|---|---|
| Cost at low volume | Free tier / per-request | ~$35/mo minimum |
| Connection model | HTTP REST (no persistent TCP) | TCP persistent connection |
| Cloud Run compatible | Yes (HTTP, no VPC required) | Requires VPC connector |
| Setup time | ~10 minutes | ~2 hours (VPC, peering) |
| Latency | ~5–20ms (global edge) | ~1ms (same region) |

For this use case (rate limiting, not a hot path cache), the extra 15ms from Upstash is irrelevant.

---

## Architecture

```
Mobile app
    │
    ▼
FastAPI (Cloud Run — N instances)
    │
    ├── require_ai_rate_limit()
    │       │
    │       ▼
    │   Upstash Redis  ◄── single source of truth for all instances
    │   (sliding-window counters keyed by athlete_id)
    │
    ▼
Gemini API
```

---

## Implementation Plan

### Step 1 — Provision Upstash Redis

1. Create an account at [console.upstash.com](https://console.upstash.com).
2. Create a new Redis database → choose the region closest to your Cloud Run deployment (e.g., `us-central1`).
3. Copy two values from the dashboard:
   - `UPSTASH_REDIS_REST_URL` — the HTTPS endpoint
   - `UPSTASH_REDIS_REST_TOKEN` — the bearer token

Add both to `backend/.env` and `backend/.env.example`.

### Step 2 — Add the Python dependency

```bash
# In backend/
pip install upstash-redis
```

Add to `requirements.txt` or `pyproject.toml`:
```
upstash-redis>=1.0.0
```

### Step 3 — Replace `RateLimiter` in `dependencies.py`

The current class:

```python
class RateLimiter:
    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        ...

    async def require(self, key: str, limit: int, window_seconds: int, detail: str):
        ...

_rate_limiter = RateLimiter()
```

Replace with a Redis-backed implementation using a **fixed-window counter with atomic INCR + EXPIRE**. This is simpler than a sliding log, handles restarts cleanly, and Upstash's latency makes it safe to use in-request:

```python
# backend/app/rate_limiter.py  (new file)
from upstash_redis import Redis
from fastapi import HTTPException
from app.config import settings
import time

_redis: Redis | None = None

def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        if not settings.UPSTASH_REDIS_REST_URL or not settings.UPSTASH_REDIS_REST_TOKEN:
            raise RuntimeError("Redis is not configured (UPSTASH_REDIS_REST_URL / TOKEN missing)")
        _redis = Redis(
            url=settings.UPSTASH_REDIS_REST_URL,
            token=settings.UPSTASH_REDIS_REST_TOKEN,
        )
    return _redis


async def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Fixed-window counter: increments an atomic counter; sets TTL on first write.
    Returns True if the request is allowed.
    """
    r = _get_redis()
    # INCR is atomic; if the key doesn't exist Redis creates it at 0 then increments.
    count = r.incr(key)
    if count == 1:
        # First request in this window — set the expiry.
        r.expire(key, window_seconds)
    return count <= limit


async def require_rate_limit(key: str, limit: int, window_seconds: int, detail: str) -> None:
    allowed = await check_rate_limit(key, limit, window_seconds)
    if not allowed:
        raise HTTPException(status_code=429, detail=detail)
```

Update `require_ai_rate_limit` in `dependencies.py`:

```python
# Before (in-memory)
async def require_ai_rate_limit(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
):
    await _rate_limiter.require(
        key=f"{athlete_id}:ai:minute",
        limit=config.rate_limit_rpm,
        window_seconds=60,
        detail=f"Rate limit exceeded: max {config.rate_limit_rpm} AI requests per minute.",
    )
    await _rate_limiter.require(
        key=f"{athlete_id}:ai:hour",
        limit=config.rate_limit_rph,
        window_seconds=3600,
        detail=f"Rate limit exceeded: max {config.rate_limit_rph} AI requests per hour.",
    )

# After (Redis)
from app.rate_limiter import require_rate_limit

async def require_ai_rate_limit(
    athlete_id: str = Depends(get_current_athlete),
    config: UserConfig = Depends(get_user_config),
):
    await require_rate_limit(
        key=f"{athlete_id}:ai:minute",
        limit=config.rate_limit_rpm,
        window_seconds=60,
        detail=f"Rate limit exceeded: max {config.rate_limit_rpm} AI requests per minute.",
    )
    await require_rate_limit(
        key=f"{athlete_id}:ai:hour",
        limit=config.rate_limit_rph,
        window_seconds=3600,
        detail=f"Rate limit exceeded: max {config.rate_limit_rph} AI requests per hour.",
    )
```

### Step 4 — Add config fields

In `backend/app/config.py`, add:

```python
# --- Upstash Redis (rate limiting) ---
UPSTASH_REDIS_REST_URL: Optional[str] = None
UPSTASH_REDIS_REST_TOKEN: Optional[str] = None
```

In `backend/.env.example`, add:

```env
# Upstash Redis — required for production rate limiting across multiple Cloud Run instances
UPSTASH_REDIS_REST_URL="https://your-db-name.upstash.io"
UPSTASH_REDIS_REST_TOKEN="your_upstash_token"
```

### Step 5 — Graceful fallback for development

To avoid requiring Redis in local dev, add a fallback. If the Redis env vars are missing, fall back to the in-memory limiter:

```python
# In app/rate_limiter.py — updated check_rate_limit
async def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    if not settings.UPSTASH_REDIS_REST_URL:
        # Dev fallback: in-memory (single instance only)
        return await _in_memory_limiter.check(key, limit, window_seconds)
    r = _get_redis()
    count = r.incr(key)
    if count == 1:
        r.expire(key, window_seconds)
    return count <= limit
```

This means local dev continues to work without any Redis setup, and the production path is clean.

### Step 6 — Deploy and verify

1. Set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` in Cloud Run environment variables (via GCP console or `gcloud run services update`).
2. Deploy. Under load, verify in the Upstash console that keys are being created with the expected TTLs.
3. Verify that the in-memory `RateLimiter` class and `_rate_limiter` global can be removed once stable.

---

## Key/TTL Design

| Key pattern | Window | Purpose |
|---|---|---|
| `{athlete_id}:ai:minute` | 60s | RPM cap per user |
| `{athlete_id}:ai:hour` | 3600s | RPH cap per user |

Keys expire automatically — no cleanup job needed.

---

## Trade-offs of Fixed-Window vs Sliding-Window

The current in-memory implementation uses a **sliding window log** (storing timestamps). Redis makes this more expensive (requires a sorted set + ZREMRANGEBYSCORE). The **fixed-window counter** (INCR + EXPIRE) is simpler and atomic but has a burst at window boundaries: a user can make `2×limit` requests by firing `limit` at the end of one window and `limit` at the start of the next.

For AI rate limiting (not financial transactions), this boundary burst is acceptable. If it becomes an issue, upgrade to Upstash's built-in rate limit SDK (`@upstash/ratelimit` — also available in Python via `upstash-ratelimit`) which implements a true sliding window using a Lua script.

---

## Estimated Effort

| Task | Time |
|---|---|
| Provision Upstash, copy credentials | 10 min |
| Write `rate_limiter.py` | 30 min |
| Update `dependencies.py` | 15 min |
| Update `config.py` + `.env.example` | 10 min |
| Local test + deploy | 30 min |
| **Total** | **~1.5 hours** |
