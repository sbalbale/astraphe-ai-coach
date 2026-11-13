# Rate Limiting — AI Context

All limiters use `RateLimiter` (`backend/app/core/rate_limiter.py`): a sliding window stored in Redis as a sorted set `rl:{key}` and updated by an atomic Lua script, so limits are shared across API replicas. Without Redis, or when a Redis call fails, it falls back to an in-process dict (per process, reset on restart). See [REDIS.md](REDIS.md).

## Limiters

### 1. Per-IP (all endpoints)
- **File:** `backend/app/main.py`, `IPRateLimitMiddleware` (singleton `_ip_rate_limiter`)
- **Keyed on:** `client_ip()`: `CF-Connecting-IP` (set by Cloudflare) when valid, else the right-most `X-Forwarded-For` hop, else `request.client.host`
- **Limit:** `settings.IP_RATE_LIMIT_RPM` (default 100 requests/min per IP)
- **Exempt:** `/health` and provider webhooks (`/v1/sync/.../webhook`, verified by signature/ownership)
- **On breach:** HTTP 429 JSON with `Retry-After: 60`

### 2. Per-athlete AI (coach endpoints)
- **File:** `backend/app/dependencies.py`, `require_ai_rate_limit` (singleton `_rate_limiter`)
- **Used on:** `POST /v1/coach/upload-document`, `/initialize`, `/message`, `/message/async`, `/stream`
- **Keys:** `{athlete}:ai:minute`, `{athlete}:ai:hour`, `{athlete}:ai:day`
- **Tier defaults (`TIER_DEFAULTS`):**

| Tier | per min | per hour | per day |
|---|---|---|---|
| `free` | 5 | 20 | 40 |
| `trial` | 6 | 60 | 150 |
| `premium` | 10 | 150 | 400 |

- **Overrides:** per user via Supabase `app_metadata.rate_limit_rpm` / `rate_limit_rph`. The daily cap is `max(tier rpd, rph)`, so an rph override also lifts it.

### 3. Per-athlete actions (non-AI)
- **File:** `backend/app/dependencies.py`, `action_rate_limit(name, limit, window_seconds, detail)`; key `{athlete}:{name}`
- **Used on (per hour):** provider backfills (`backfill:garmin|whoop|whoop_bio|strava|intervals`, 3), `reprocess` (6), `refresh_strain` (10), `garmin_login` (5), `garmin_mfa` (10), `hydrate_streams` (30), `refetch_strava` (20)

### 4. Generated analyses
- **File:** `backend/app/routers/analysis.py`, `_analysis_limiter`
- **Limits:** 30 generated analyses per hour and 120 per day per athlete (`ANALYSIS_LLM_PER_HOUR` / `_PER_DAY`); cache hits are free.

### Related quotas (not `RateLimiter`)
- `services/gemini_quota.py`: one RPM window per Gemini model for the whole server (`gemini_rpm:{model}` in Redis).
- `services/plan_import.py`: `PLAN_IMPORTS_PER_DAY` (default 5) per athlete, plus a per-model "daily quota exhausted" flag.
- `POST /v1/notifications/test`: one per 30 s, enforced through a `notification_log` claim.

## Middleware stack order

Starlette wraps in reverse `add_middleware` order (last added = outermost):

```
Request in  →  GZip  →  CORS  →  IPRateLimit  →  SecurityHeaders  →  routes
```

Key consequences:
- OPTIONS preflights are answered by CORS before reaching the IP limiter.
- 429 responses from the IP limiter still get CORS headers.

## What is NOT covered

Supabase auth calls (`signIn`, `signUp`, `resetPasswordForEmail`, `updateUser`) go directly from the client to Supabase Auth (GoTrue) and bypass FastAPI. Their limits are GoTrue settings: `[auth.rate_limit]` in `supabase/config.toml` for local Supabase (e.g. `sign_in_sign_ups`, `token_refresh`, `email_sent`), or the Auth rate limit settings of the deployed instance.

## Tuning

Change `IP_RATE_LIMIT_RPM` in the backend environment (no code change). Tier, action and analysis limits are constants in code.
