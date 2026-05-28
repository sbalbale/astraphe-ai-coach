# Security Audit — ASTRAPHE AI Coach
**Date:** 2026-05-19  
**Auditor:** Claude (vibe-security skill)  
**Scope:** Full codebase — backend (FastAPI/Python), mobile (SvelteKit/Capacitor), Supabase schema/RLS, environment files  
**Commit:** `a5fe7a3` (main branch, clean working tree)

---

## Executive Summary

The codebase has a well-structured security posture for an early-stage AI coaching app: Row-Level Security is enabled on all Supabase tables, the admin API reads tier/model/rate-limit from server-controlled `app_metadata` (not user-mutable `user_metadata`), and rate limiting is applied on all AI endpoints. The most significant issues are an **unauthenticated public API endpoint**, **missing webhook signature verification on Strava**, and **a silent auth-failure pattern** that could mask broken auth in future routes.

---

## Findings

### 🔴 HIGH — `backend/app/routers/workouts.py:109` — Unauthenticated `/v1/workouts/calculate-tss`

The `calculate-tss` endpoint has no `Depends(get_current_athlete)` dependency and is completely unauthenticated. Any anonymous caller on the internet can POST arbitrary `WorkoutPayload` data to trigger server-side computation.

**Impact:** Low-cost denial-of-service; no data exposure. However, it leaks API surface to unauthenticated callers and sets a precedent for other endpoints that might accidentally omit auth.

```python
# Before — no auth, anyone can call this
@router.post("/calculate-tss")
async def process_workout(payload: WorkoutPayload):
    if payload.workout_type.lower() == "cycling":
        tss = compute_tss_power(...)
        return {"status": "success", "data": {"calculated_tss": tss}}
    raise HTTPException(status_code=400, detail="Not implemented.")

# After — require an authenticated athlete
@router.post("/calculate-tss")
async def process_workout(
    payload: WorkoutPayload,
    athlete_id: str = Depends(get_current_athlete),
):
    if payload.workout_type.lower() == "cycling":
        tss = compute_tss_power(...)
        return {"status": "success", "data": {"calculated_tss": tss}}
    raise HTTPException(status_code=400, detail="Not implemented.")
```

---

### 🔴 HIGH — `backend/app/routers/sync.py:563` — Strava Webhook Accepts Unauthenticated Payloads

The Strava POST webhook handler (`/v1/sync/strava/webhook`) accepts any request without verifying the origin. Unlike the WHOOP webhook (which uses HMAC-SHA256 verification) and the Garmin webhook (which has HMAC verification guarded by a secret), the Strava webhook performs no signature check.

**Impact:** An attacker who knows the webhook URL can:
1. Send a fake `aspect_type: "delete"` event with any `object_id` to null out `strava_activity_id` on workout rows (data corruption).
2. Send a fake `aspect_type: "create"` event to trigger a background call to Strava's API to ingest an activity — this fails if the activity doesn't exist, but it wastes resources and generates spurious API calls against the stored user token.

Strava does not sign webhook payloads (unlike WHOOP), but you can mitigate this with a shared secret header or by requiring an `X-Hub-Signature` via a custom mechanism.

```python
# Before — no verification
@router.post("/strava/webhook")
async def strava_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    payload = await request.json()
    ...

# After — verify a shared secret in a custom header (add STRAVA_WEBHOOK_TOKEN to env)
STRAVA_WEBHOOK_TOKEN = settings.STRAVA_WEBHOOK_VERIFY_TOKEN  # reuse existing config field

@router.post("/strava/webhook")
async def strava_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    # Strava doesn't sign payloads; validate a shared secret in a custom header
    # (set this header in Strava's webhook configuration dashboard)
    token = request.headers.get("X-Strava-Token", "")
    if STRAVA_WEBHOOK_TOKEN and not secrets.compare_digest(token, STRAVA_WEBHOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    payload = await request.json()
    ...
```

> **Note:** If you cannot add a custom header to Strava's webhook delivery, an alternative is to validate the `owner_id` field against known registered Strava athlete IDs in your database before processing any event.

---

### 🔴 HIGH — `backend/app/dependencies.py:197` — Silent Auth Failure in `get_user_config` Returns Empty `UserConfig`

When any exception occurs during auth in `get_user_config`, the function silently returns a default `UserConfig` with `user_id=""` and `is_admin=False` rather than raising HTTP 401:

```python
# Current — silently absorbs all exceptions, including auth failures
except Exception:
    defaults = TIER_DEFAULTS["free"]
    return UserConfig(
        user_id="",          # ← empty string, not the real user
        tier="free",
        gemini_model=fallback_model,
        gemini_analysis_model=fallback_analysis,
        rate_limit_rpm=defaults["rpm"],
        rate_limit_rph=defaults["rph"],
        is_admin=False,
    )
```

**Current mitigations that partially limit exploitability:**
- All AI/coach/analysis endpoints also inject `get_current_athlete`, which does correctly raise 401 on auth failure.
- The admin router uses its own separate `get_admin_user` dependency that raises 403 correctly.

**Why this is still dangerous:** Any future route added with `get_user_config` but without `get_current_athlete` would silently treat a bad token as a free-tier anonymous user. The silent failure pattern is hard to audit at scale.

```python
# After — distinguish transient errors from auth errors
async def get_user_config(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> UserConfig:
    token = credentials.credentials
    fallback_model = (settings.GEMINI_MODEL or "").strip() or "gemma-4-31b-it"
    fallback_analysis = (settings.GEMINI_ANALYSIS_MODEL or "").strip() or "gemini-flash-lite-latest"

    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        if u is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        app_meta = getattr(u, "app_metadata", None) or {}
        # ... rest of logic ...
    except HTTPException:
        raise
    except Exception:
        # Only absorb transient/non-auth errors; re-raise auth failures
        # For robustness in transient DB blips, fall back to free-tier defaults
        # but ONLY if we already have a validated athlete_id from get_current_athlete.
        defaults = TIER_DEFAULTS["free"]
        return UserConfig(
            user_id="",
            tier="free",
            gemini_model=fallback_model,
            gemini_analysis_model=fallback_analysis,
            rate_limit_rpm=defaults["rpm"],
            rate_limit_rph=defaults["rph"],
            is_admin=False,
        )
```

> The safer fix is to have `get_user_config` accept the already-validated `athlete_id` from `get_current_athlete` as an input, making the auth dependency explicit and non-bypassable.

---

### 🟡 MEDIUM — `backend/app/dependencies.py:116` — Auth Development Fallback (`TEST_ATHLETE_ID`) Triggered on Any Exception

When `APP_ENV == "development"` and any exception occurs during JWT validation (not just auth failures), the code falls back to `TEST_ATHLETE_ID`:

```python
except Exception as e:
    print(f"Auth error: {str(e)}")
    if settings.APP_ENV == "development" and settings.TEST_ATHLETE_ID:
        print(f"WARNING: Falling back to TEST_ATHLETE_ID: {settings.TEST_ATHLETE_ID}")
        # ... grants access as TEST_ATHLETE_ID ...
```

**Impact:** If `APP_ENV` is accidentally set to `"development"` in a staging or production environment (e.g., from a misconfigured `.env` file), any request with a broken or missing token authenticates as `TEST_ATHLETE_ID`. This bypasses all authentication for that athlete's data.

```python
# After — keep the fallback but make APP_ENV = "development" harder to accidentally deploy
# In config.py, add a production safety check:
if settings.APP_ENV == "production" and settings.TEST_ATHLETE_ID:
    raise RuntimeError("TEST_ATHLETE_ID must not be set in production")
```

Additionally, consider replacing the broad `except Exception` with specific JWT/auth exception types so that only token validation errors trigger the fallback, not network errors or misconfiguration.

---

### 🟡 MEDIUM — `backend/app/dependencies.py:104` — PII Logged to Stdout in Every Auth Request

Every authenticated request logs the `user_id` and the full DB response to stdout:

```python
user_id = user.user.id
print(f"Auth DEBUG: user_id={user_id}")

athlete_res = db.table("athletes").select("id").eq("user_id", user_id).execute()
print(f"Auth DEBUG: athlete_res={athlete_res.data}")
```

**Impact:** In production (especially Cloud Run where stdout is ingested by Cloud Logging), every API call writes the authenticated user's UUID to logs. Log retention, log access controls, and log export paths could all result in user ID leakage. If log aggregation is compromised, the full mapping of tokens → user IDs is exposed.

```python
# After — remove or gate the debug lines behind an env flag
if settings.APP_ENV == "development":
    print(f"Auth DEBUG: user_id={user_id}")
    print(f"Auth DEBUG: athlete_res={athlete_res.data}")
```

---

### 🟡 MEDIUM — `backend/app/routers/sync.py:676` — OAuth Callbacks Leak Internal Error Messages

Both the WHOOP and Strava OAuth callbacks catch all exceptions and return the raw error string to the browser:

```python
# WHOOP callback (line 676)
except Exception as e:
    print(f"[whoop.oauth.callback] ERROR: {repr(e)}")
    return {"status": "error", "message": str(e)}

# Strava callback (line 789)
except Exception as e:
    print(f"[strava.oauth.callback] ERROR: {repr(e)}")
    return {"status": "error", "message": str(e)}
```

**Impact:** Internal stack traces, database error messages, Supabase URLs, or table names could be returned to the client. This aids reconnaissance.

```python
# After — return a generic message; log the full error server-side
except Exception as e:
    print(f"[whoop.oauth.callback] ERROR: {repr(e)}")
    return {"status": "error", "message": "OAuth connection failed. Please try again."}
```

---

### 🟡 MEDIUM — `backend/.env:28` — `WHOOP_WEBHOOK_SECRET` Identical to `WHOOP_CLIENT_SECRET`

In `backend/.env`, `WHOOP_CLIENT_SECRET` and `WHOOP_WEBHOOK_SECRET` are set to the same value:

```env
WHOOP_CLIENT_SECRET="cceb65078087259747d6f3d5f3e8e4950a2de738b249451c92810b085845b7b0"
WHOOP_WEBHOOK_SECRET="cceb65078087259747d6f3d5f3e8e4950a2de738b249451c92810b085845b7b0"
```

**Impact:** These serve different purposes. `WHOOP_CLIENT_SECRET` is an OAuth secret used for token exchange; it should never leave your server. `WHOOP_WEBHOOK_SECRET` is a shared secret used to verify that incoming webhook payloads come from WHOOP. If either is compromised, both are compromised — an attacker who steals one can impersonate either your OAuth client or forge webhook events.

**Fix:** Generate a new, distinct random secret for `WHOOP_WEBHOOK_SECRET` and update it in the WHOOP developer portal.

```env
# After — distinct secrets for distinct purposes
WHOOP_CLIENT_SECRET="<oauth_client_secret>"
WHOOP_WEBHOOK_SECRET="<independent_random_string_registered_with_whoop>"
```

---

### 🟡 MEDIUM — `supabase/migrations/20260429000002_coach_chat_history.sql:48` — `coach-uploads` Bucket Was Created as `public = true`

The original migration created the coach file upload bucket with `public = true`:

```sql
INSERT INTO storage.buckets (id, name, public)
VALUES ('coach-uploads', 'coach-uploads', true)   -- ← publicly readable by URL
```

This was corrected in a later migration (`20260519120000_coach_uploads_private.sql`), but there was a window during which all files uploaded to this bucket were publicly accessible by anyone who knew the path. Since Supabase public bucket URLs follow a predictable pattern (`/storage/v1/object/public/coach-uploads/<path>`), and the path includes `auth.uid()`, the exposure was limited — but it was non-zero.

**No code fix needed** (already resolved in `20260519120000`). However, if any health/biometric images were uploaded during this window, they should be considered potentially exposed and users should be notified per applicable privacy regulations.

---

### 🟡 MEDIUM — `backend/app/main.py` — No Security Headers on API Responses

The FastAPI app does not set standard security headers. While most responses are JSON (not rendered HTML), missing headers can still cause issues:

```python
# After — add security headers middleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

The OAuth success page (`_oauth_connected_success_response`) renders actual HTML and is particularly exposed to clickjacking without `X-Frame-Options`.

---

### 🟡 MEDIUM — `backend/app/routers/sync.py:269` — Garmin Webhook Skips Signature Verification With Placeholder Secret

The Garmin webhook verification is gated on:

```python
if garmin_secret and garmin_secret != "your_garmin_webhook_secret":
```

This is correct for the current state (Garmin not configured), but the check against a literal string `"your_garmin_webhook_secret"` is fragile. If someone configures Garmin with a real secret value and forgets to update the check, or if the comparison breaks in a code change, the verification could be silently skipped.

```python
# After — simplify: just check if a non-empty secret is configured
if garmin_secret:
    expected = hmac.new(
        garmin_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid Garmin signature")
else:
    # No secret configured — reject all Garmin webhooks until Garmin is set up
    raise HTTPException(status_code=503, detail="Garmin webhook not configured")
```

---

### 🟢 LOW — `backend/app/dependencies.py:43` — In-Memory Rate Limiter Breaks Under Horizontal Scaling

The `RateLimiter` class stores sliding windows in a Python dict:

```python
class RateLimiter:
    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)
```

**Impact:** On Cloud Run with more than one container instance, each instance has its own counter. A user can fire `limit * n_instances` requests per window across instances, bypassing per-user rate limits. The comment in the code acknowledges this; the fix is to replace with Redis (e.g., Upstash).

This is low priority for single-instance deployments, but should be addressed before scaling to multiple Cloud Run instances.

---

### 🟢 LOW — `backend/app/services/ai_coach.py` — User Messages Are Not Sanitized Before LLM Injection

User chat messages are passed directly to Gemini without filtering or truncation:

```python
# In get_coach_response_agentic
contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
```

The use of separate `system` and `user` roles in the Gemini API is the recommended mitigation for prompt injection, and it's implemented here. However:
1. There is no maximum message length enforced on `payload.message`.
2. A sufficiently long or crafted user message could attempt to override system instructions via indirect prompt injection.

```python
# After — add a client-side and server-side message length cap
class ChatMessage(BaseModel):
    message: str
    # ...

    @field_validator("message")
    @classmethod
    def validate_message_length(cls, v: str) -> str:
        if len(v) > 8000:
            raise ValueError("Message too long (max 8000 characters)")
        return v
```

---

### 🟢 LOW — `supabase/.gitignore` Does Not Independently Protect `supabase/.env`

The `supabase/.gitignore` file contains:
```
.branches
.temp
.env.keys
.env.local
.env.*.local
```

It does **not** include `.env`. The `supabase/.env` file (which contains `RESEND_SMTP_PASSWORD`) is only protected by the root `.gitignore` rule (`.env`). While the root `.gitignore` is effective, a developer working in the `supabase/` subdirectory with tooling that uses the local `.gitignore` might not realize the file is excluded.

```diff
# supabase/.gitignore
 .branches
 .temp
 .env.keys
 .env.local
 .env.*.local
+.env
+.env.*
```

---

## Positive Security Findings

The following security controls are correctly implemented and should be maintained:

| Area | Status |
|------|--------|
| Supabase RLS | ✅ Enabled on all tables: `athletes`, `workouts`, `biometrics`, `tss_history`, `training_plans`, `oauth_tokens`, `coach_conversations`, `coach_messages`, `activity_streams`, `activity_laps`, `athlete_analyses` |
| Admin flag in `app_metadata` | ✅ Correctly read from `app_metadata` (server-controlled), never from `user_metadata` |
| Tier gating | ✅ Tier read from `app_metadata`, never from client request body |
| Rate limiting on AI endpoints | ✅ Sliding-window per-user RPM + RPH via `require_ai_rate_limit` dependency |
| WHOOP webhook signature | ✅ HMAC-SHA256 verified on every WHOOP POST webhook |
| Redirect allowlist | ✅ `_ALLOWED_RETURN_HOSTS` allowlist prevents open redirect on OAuth return URL |
| CORS | ✅ Explicit origin allowlist; `allow_credentials=True` paired with specific origins, not `*` |
| Secret env vars | ✅ All `.env` files are git-ignored by root `.gitignore` |
| Coach data isolation | ✅ All DB queries filter by `athlete_id` from verified JWT |
| Admin DB separation | ✅ Service-role client (`get_admin_db`) used only in admin endpoints and webhook handlers |
| OAuth state validation | ✅ `athlete_id` parsed and checked against DB before saving tokens |
| coach-uploads bucket | ✅ Set to private (migration `20260519120000`) |
| Storage RLS | ✅ Objects scoped to `auth.uid()` via `split_part(name, '/', 2)` |

---

## Priority Fix Order

| # | Severity | File | Issue | Effort |
|---|----------|------|-------|--------|
| 1 | 🔴 HIGH | `workouts.py:109` | Add `Depends(get_current_athlete)` to `calculate-tss` | 2 min |
| 2 | 🔴 HIGH | `sync.py:563` | Add Strava webhook verification (shared secret or owner_id check) | 30 min |
| 3 | 🔴 HIGH | `dependencies.py:197` | Distinguish transient failures from auth failures in `get_user_config` | 1 hour |
| 4 | 🟡 MEDIUM | `dependencies.py:116` | Add production guard: refuse to start if `TEST_ATHLETE_ID` set when `APP_ENV=production` | 10 min |
| 5 | 🟡 MEDIUM | `dependencies.py:104` | Remove or gate `Auth DEBUG:` print statements | 5 min |
| 6 | 🟡 MEDIUM | `sync.py:676,789` | Replace bare `str(e)` in OAuth error responses | 5 min |
| 7 | 🟡 MEDIUM | `.env` | Rotate `WHOOP_WEBHOOK_SECRET` to be distinct from `WHOOP_CLIENT_SECRET` | 10 min |
| 8 | 🟡 MEDIUM | `main.py` | Add security headers middleware | 15 min |
| 9 | 🟡 MEDIUM | `sync.py:269` | Simplify Garmin placeholder check | 10 min |
| 10 | 🟢 LOW | `dependencies.py:43` | Plan Redis migration for rate limiter before horizontal scale | Backlog |
| 11 | 🟢 LOW | `ai_coach.py` | Add server-side message length validation | 10 min |
| 12 | 🟢 LOW | `supabase/.gitignore` | Add `.env` and `.env.*` patterns | 2 min |

---

*Generated by `/vibe-security` skill — ASTRAPHE AI Coach codebase, commit `a5fe7a3`*
