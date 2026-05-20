# Redis

Redis backs the rate limiters. All rate-limit state lives in Redis so it's consistent across multiple backend instances (Cloud Run scale-out).

---

## Local development

Start Redis in Docker (one command, no install needed):

```bash
docker compose up -d redis
```

Then add to `backend/.env`:
```
REDIS_URL="redis://localhost:6379"
```

Stop it when done:
```bash
docker compose down
```

---

## Production (Upstash)

1. Go to [upstash.com](https://upstash.com) → **Create Database** → pick a region close to your Cloud Run service
2. Copy the **Redis URL** from the console (starts with `rediss://`)
3. Add it to Cloud Run / Secret Manager:
   ```
   REDIS_URL="rediss://default:<token>@<host>.upstash.io:6380"
   ```

That's it — same `redis-py` client, same interface, TLS handled automatically.

---

## What uses Redis

| Feature | Key pattern | Window |
|---|---|---|
| Per-IP rate limit (all endpoints) | `rl:ip:<ip>` | 60 s |
| Per-user AI rate limit (minute) | `rl:<athlete_id>:ai:minute` | 60 s |
| Per-user AI rate limit (hour) | `rl:<athlete_id>:ai:hour` | 3600 s |

All use a **sliding-window sorted set** — accurate, no thundering-herd on window reset.

---

## Fallback behaviour

If `REDIS_URL` is not set (or Redis is unreachable), both rate limiters fall back to an **in-process dict**. This means:
- Rate limits still work for single-instance deployments
- State is lost on restart
- Limits are not shared across multiple instances

The health endpoint reports Redis status:
```
GET /health
→ { "status": "healthy", "redis": "connected" | "unavailable" }
```

---

## Implementation

| File | Purpose |
|---|---|
| `backend/app/core/redis.py` | Lazy async client singleton, `ping_redis()`, `close_redis()` |
| `backend/app/core/rate_limiter.py` | `RateLimiter` class — Redis sorted set + in-memory fallback |
| `docker-compose.yml` | Local Redis service (`redis:7-alpine`, port 6379) |
