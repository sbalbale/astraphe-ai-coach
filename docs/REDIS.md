# Redis

Redis is optional in local development and recommended in production/multi-container deployments.

## Uses

| Feature | Purpose |
|---|---|
| Global IP rate limit | Shared sliding-window request limit across API instances. |
| AI rate limits | Per-athlete minute/hour sliding windows for coach and analysis-heavy routes. |
| Activity stream cache | Cached Strava/activity stream payloads for workout detail views. |
| Workout zone cache | Cached zone distribution responses for repeated reads. |

Rate limiting falls back to an in-process dictionary if Redis is absent. That is fine for single-process local dev, but it is not shared across instances and resets on restart.

## Local Development

Start Redis from the repository root:

```bash
docker compose up -d redis
```

Add this to `backend/.env`:

```env
REDIS_URL=redis://localhost:6379
```

Stop Redis:

```bash
docker compose down
```

## Production

Use any Redis-compatible URL. Upstash-style TLS URLs work:

```env
REDIS_URL=rediss://default:<token>@<host>.upstash.io:6380
```

For the current Proxmox/docker-compose deployment, provide `REDIS_URL` through the server environment used by the `astrape-api` container.

## Health Check

`GET /health` reports Redis state:

```json
{
  "redis": "connected"
}
```

If Redis is unset or unreachable, the value is `unavailable` and the API continues with the in-memory fallback.

## Implementation

| File | Purpose |
|---|---|
| `backend/app/core/redis.py` | Async Redis client lifecycle and ping. |
| `backend/app/core/rate_limiter.py` | Redis sorted-set sliding window plus memory fallback. |
| `backend/app/services/analysis_cache.py` | Cache/fingerprint helpers for AI analysis. |
| `backend/app/routers/activity_detail.py` | Activity stream and zone cache use. |
| `docker-compose.yml` | Local Redis service. |
