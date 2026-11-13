# Redis

Redis is optional in local development and required in production, where more than one API replica runs: it shares rate limits, caches, locks and short-lived state across replicas and restarts.

Without Redis (or when a Redis call fails) nothing raises. Rate limits, quotas, locks and coach progress fall back to process memory (correct for one process, not shared). Caches become misses. The OAuth state nonce check is skipped (the state's 10-minute expiry still applies).

## Clients

`backend/app/core/redis.py`:

- `get_redis()`: lazy `redis.asyncio.Redis` client, or `None` when `REDIS_URL` is unset. No connection is made until the first command.
- `get_sync_redis()`: blocking `redis.Redis` client for code running in worker threads (Garmin login, Gemini quota, plan import, coach context).
- `ping_redis()`: used by `/health`. `close_redis()`: called on shutdown.

Both clients use `decode_responses=True` and 2 s connect/socket timeouts. Always guard with `if r is not None` and treat errors as "Redis unavailable".

## Keys

| Key | Type / TTL | Purpose | Code |
|---|---|---|---|
| `rl:{key}` | ZSET, window + 1 s | Sliding-window rate limits (atomic Lua). See below for the keys. | `core/rate_limiter.py` |
| `state:{athlete}` | 60 s | Athlete state (CTL/ATL/readiness card). | `routers/athlete.py` |
| `profile:{athlete}` | 5 min | Athlete profile. | `routers/athlete.py` |
| `zones:{athlete}` | 5 min | Athlete zone definitions. | `routers/athlete.py` |
| `zones_version:{athlete}` | counter, no TTL | Version stamped into workout detail and zone keys; incremented on workout changes and profile updates. | `routers/athlete.py`, `core/cache_invalidation.py` |
| `detail:{athlete}:v{N}:{workout}` | 24 h (5 min if the workout has no streams) | Workout detail payload (streams, laps, intervals, zones). `N` = `zones_version`. | `routers/activity_detail.py` |
| `zones:workout:{athlete}:v{N}:{workout}` | 6 h | Workout HR zone distribution. | `routers/activity_detail.py` |
| `streams:{athlete}:{workout}` | 24 h | Workout stream row. | `routers/activity_detail.py` |
| `body_version:{athlete}` | counter, no TTL | Retires every `body:` key and the coach context when the athlete's data changes. | `core/body_cache.py` |
| `body:{athlete}:v{N}:{name}` | see below | Body screens and start-up lists. `N` = `body_version`. | `core/body_cache.py` |
| `gemini_rpm:{model}` | ZSET, window + 1 s | One sliding RPM window per model for all replicas (Lua on Redis's own clock). | `services/gemini_quota.py` |
| `plan_import_exhausted:{model}` | expires at the next Pacific midnight (Google's daily reset) | Model's daily plan-import quota is used up. | `services/plan_import.py` |
| `plan_imports:{athlete}:{day}` | counter, 2 days | Per-athlete plan imports per day (`PLAN_IMPORTS_PER_DAY`). | `services/plan_import.py` |
| `regen:{athlete}:{scope}` | SET NX, 120 s | AI analysis regeneration lock; released only by its holder (token check in Lua), so one replica regenerates. | `routers/analysis.py` |
| `garmin_mfa:{state_token}` | 5 min | Encrypted pending Garmin login awaiting the MFA code; read with GETDEL so it is used once, on whichever replica gets the code. | `services/garmin.py` |
| `coach:progress:{athlete}:{conversation}` | list, 10 min, last 60 events | Coach reply progress events polled by the chat page. | `services/coach_progress.py` |
| `coach:watching:{athlete}:{conversation}` | 15 s | Athlete has the thread open; suppresses the coach reply push. | `services/coach_progress.py` |
| `oauth_state_used:{nonce}` | SET NX, 11 min | One-use OAuth callback state (replay protection). | `services/oauth_state.py` |

`body:` names and TTLs:

| Name | TTL | Route |
|---|---|---|
| `hrday:{date}` | 60 s for today, 30 min for past days | `GET /v1/biometrics/heart-rate` |
| `weight:{today}` | 10 min | `GET /v1/weight` |
| `workouts:{limit}` | 2 min | first page of `GET /v1/workouts` |
| `biometrics:{limit}` | 2 min | first page of `GET /v1/biometrics` |

### Invalidation

- `invalidate_athlete_caches()` (`core/cache_invalidation.py`) deletes `state:` (and `profile:` when asked), increments `zones_version:` for workout changes, always increments `body_version:`, and drops this process's coach context.
- Callers of `invalidate_athlete_caches()`: `routers/biometrics.py`, `routers/sync.py`, `routers/weight.py`, `routers/workouts.py`, `services/whoop_backfill.py`.
- `bump_body_cache()` / `bump_body_cache_sync()` only increment `body_version:`; called from `services/processing.py` (TSS recalculation, biometrics saves), `services/garmin.py` and `routers/workouts.py`.
- The coach context cache (`services/ai_coach.py`) stays in process memory but is stamped with `body_version`, so a write on either replica retires it on the next read. TTL is 10 min with Redis, 60 s without.
- TTLs are the backstop for any writer that does not bump.

### Rate-limit keys

All per-athlete and per-IP limits use `RateLimiter` (`core/rate_limiter.py`), stored as `rl:{key}`:

- `rl:{ip}`: global per-IP limit, `IP_RATE_LIMIT_RPM` (default 100) per minute, in `IPRateLimitMiddleware` (`app/main.py`).
- `rl:{athlete}:ai:minute|hour|day`: AI endpoints (`require_ai_rate_limit` in `dependencies.py`).
- `rl:{athlete}:{action}`: expensive non-AI actions (`action_rate_limit`), e.g. backfills, reprocessing, Garmin login/MFA, stream hydration.

See [RATE_LIMITING.md](RATE_LIMITING.md) for limits and middleware order.

## Memory Policy

Production Redis runs with `--maxmemory 256mb --maxmemory-policy volatile-lru`: under memory pressure only keys with a TTL are evicted (cache entries, rate-limit windows), never the TTL-less version counters (`zones_version:`, `body_version:`). Every cache key therefore needs a TTL. (The server config is not in this repo.)

## Local Development

Start Redis from the repository root (`docker-compose.yml`, `redis:7-alpine` with AOF persistence):

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

## Production

The API runs in the maintainer's k3s cluster (namespace `astraphe`), deployed by `.github/workflows/deploy.yml`. `REDIS_URL` comes from the deployed environment, not the workflow; the Redis deployment and its hostname are not defined in this repo. See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Health Check

`GET /health` reports Redis state:

```json
{
  "redis": "connected"
}
```

If Redis is unset or unreachable, the value is `unavailable` and the API continues with the fallbacks above. Startup logs the Redis URL without credentials.
