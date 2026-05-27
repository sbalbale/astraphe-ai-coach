# Redis

Redis is optional in local development and **required in production** (self-hosted on Proxmox) so rate limits and activity stream caches are shared across API restarts.

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
REDIS_URL=redis://127.0.0.1:6379
```

Stop Redis:

```bash
docker compose down
```

## Production (self-hosted)

Production runs on the Proxmox Docker host (`~/astrape`), deployed via [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml). The API container must use the **Docker service hostname** for Redis on the shared `astrape` network:

```env
REDIS_URL=redis://astrape-redis:6379
```

| Container | Image | Role |
|-----------|-------|------|
| `astrape-api` | GHCR `astrape-api` | FastAPI |
| `astrape-redis` | `redis:7-alpine` | Cache + rate limits |

Set `REDIS_URL` in the compose environment for `astrape-api` on the server (not `localhost:6379` from inside the API container unless you intentionally bridge host networking).

See [DEPLOYMENT.md](./DEPLOYMENT.md) for the full deploy model.

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
