# Rate Limiting — AI Context

## Two separate limiters

### 1. IP-based (all endpoints)
- **File:** `backend/app/main.py` — `IPRateLimitMiddleware`
- **Keyed on:** real client IP (reads `X-Forwarded-For` first, then `request.client.host`)
- **Limit:** `settings.IP_RATE_LIMIT_RPM` (default: 100 req/min per IP)
- **Exempt:** `/health`
- **Response on breach:** `HTTP 429` JSON with `Retry-After: 60` header

### 2. Per-user AI (AI endpoints only)
- **File:** `backend/app/dependencies.py` — `RateLimiter`, `require_ai_rate_limit`
- **Keyed on:** `athlete_id`
- **Limits:** vary by tier (`free`: 5 rpm/20 rph, `trial`: 15/75, `premium`: 40/200)
- **Overridable:** per-user via `app_metadata.rate_limit_rpm` / `rate_limit_rph` in Supabase

## Middleware stack order

Starlette wraps in reverse `add_middleware` order (last added = outermost):

```
Request in  →  CORSMiddleware  →  IPRateLimitMiddleware  →  SecurityHeadersMiddleware  →  routes
Response out ←  CORSMiddleware  ←  IPRateLimitMiddleware  ←  SecurityHeadersMiddleware  ←  routes
```

Key consequences:
- OPTIONS preflights are short-circuited by CORS before reaching the IP limiter
- 429 responses from the IP limiter still receive CORS headers (browser clients work correctly)

## What is NOT covered

**Supabase auth endpoints** (`signIn`, `signUp`, `resetPasswordForEmail`, `updateUser`) go directly from the client to Supabase — they bypass FastAPI entirely. To rate limit these, configure **Auth Rate Limits** in the Supabase dashboard:
- Project Settings → Auth → Rate Limits
- Key ones: "Sign ups per hour", "OTP / Magic Link sends per hour", "Token refresh" 

## Scaling caveat

Both limiters use in-memory sliding windows (`asyncio.Lock` + list of timestamps). They reset on server restart and are **not shared across Cloud Run instances**. For multi-instance deployments, replace `RateLimiter` with a Redis-backed counter. The `_rate_limiter` and `_ip_rate_limiter` instances are the only things that need replacing — the rest of the code is interface-compatible.

## Tuning

Change `IP_RATE_LIMIT_RPM` in `.env`:
```
IP_RATE_LIMIT_RPM=100
```
No code change required.
