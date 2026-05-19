# Security Fixes

All backend fixes have been implemented. Two items (mobile token storage and the storage
bucket migration) require a one-time manual step described below.

---

## ✅ Critical — Fixed

### 1. Webhook signature verification — `backend/app/routers/sync.py`

**WHOOP** — `verify_webhook_signature()` (already implemented in `services/whoop.py`) is
now called before any payload processing. Invalid or missing signatures return 401.

**Garmin** — HMAC-SHA256 over the request body with `GARMIN_WEBHOOK_SECRET` is now
verified when the secret is configured. Set the real secret in `.env`:
```
GARMIN_WEBHOOK_SECRET="<your garmin webhook secret>"
```

**Strava** — Strava's POST webhooks do not include a cryptographic signature header.
Security relies on Strava only posting to your registered callback URL (set during
subscription setup). The `owner_id` in every payload is validated against a known
athlete in the database before any work is done.

---

## ✅ High — Fixed

### 2. Tier stored in `app_metadata` only — `backend/app/dependencies.py`

`get_user_config()` now reads exclusively from `app_metadata`. The old
`user_meta.get("tier")` fallback has been removed. `user_metadata` is writable by
the user themselves and must never be trusted for access control.

### 3. Gemini model from `app_metadata` only — `backend/app/dependencies.py`

Same fix. `user_metadata.gemini_model` is no longer consulted. Per-user model
overrides are set by admins via `PATCH /v1/admin/users/{user_id}`.

### 4. OAuth authorize endpoints require authentication — `backend/app/routers/sync.py`

`GET /v1/sync/oauth/whoop/authorize` and `GET /v1/sync/oauth/strava/authorize` now
use `Depends(get_current_athlete)`. The `athlete_id` is derived from the JWT, not
from a query parameter an attacker could supply.

### 5. Open redirect in OAuth callbacks fixed — `backend/app/routers/sync.py`

`web_return` is now validated through `_safe_web_return()` against `_ALLOWED_RETURN_HOSTS`
before any redirect. Invalid or off-allowlist URLs fall through to the default deep-link
response. Add your production domain to `_ALLOWED_RETURN_HOSTS` in `sync.py`.

---

## ✅ Medium — Fixed

### 6. CORS wildcard replaced — `backend/app/main.py`

`allow_origins=["*"]` with `allow_credentials=True` was invalid per the CORS spec.
`ALLOWED_ORIGINS` now lists the Capacitor and local-dev origins explicitly. Add your
production domain to `ALLOWED_ORIGINS` in `main.py` before deploying.

### 7. Per-user rate limiting on AI endpoints — `backend/app/dependencies.py` + `coach.py`

`require_ai_rate_limit` is a FastAPI dependency applied to `/v1/coach/initialize`,
`/v1/coach/message`, and `/v1/coach/stream`. Limits are enforced with a
sliding-window in-memory limiter (single-instance safe). Default limits by tier:

| Tier    | Per minute | Per hour |
|---------|-----------|---------|
| free    | 5         | 20      |
| trial   | 15        | 75      |
| premium | 40        | 200     |

Override any user's limits via the admin API:
```
PATCH /v1/admin/users/{user_id}
{"rate_limit_rpm": 60, "rate_limit_rph": 500}
```

**Note:** For multi-instance deployments (Cloud Run with >1 replica), replace
`_rate_limiter` in `dependencies.py` with a Redis-backed sliding-window counter.

---

## ✅ Admin system — New feature (`backend/app/routers/admin.py`)

All three per-user controls (tier, AI model, rate limits) are managed through a
protected admin API. Only users with `app_metadata.is_admin = true` can call it.

### Bootstrapping the first admin

Run this once in the Supabase dashboard SQL editor (or via the service-role client):
```sql
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"is_admin": true}'
WHERE email = 'your-admin@email.com';
```

### Admin API endpoints

All endpoints require a valid JWT from a user with `is_admin = true`.

#### List users
```
GET /v1/admin/users?page=1&per_page=50
```

#### Get one user
```
GET /v1/admin/users/{user_id}
```

Response shape:
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "display_name": "Jane Doe",
  "config": {
    "tier": "free",
    "gemini_model": null,
    "gemini_analysis_model": null,
    "rate_limit_rpm": 5,
    "rate_limit_rph": 20,
    "is_admin": false
  }
}
```

#### Update user config
```
PATCH /v1/admin/users/{user_id}
```

All fields are optional — only what you include is changed:
```json
{
  "tier": "premium",
  "gemini_model": "gemini-2.5-pro",
  "gemini_analysis_model": "gemini-2.5-flash",
  "rate_limit_rpm": 60,
  "rate_limit_rph": 500,
  "is_admin": false
}
```

- Pass an **empty string** for `gemini_model` / `gemini_analysis_model` to clear the
  per-user override and revert to the server `.env` default.
- Pass `null` for `rate_limit_rpm` / `rate_limit_rph` to revert to the tier default.

#### Clear a single override
```
DELETE /v1/admin/users/{user_id}/config/{field}
```
Valid fields: `gemini_model`, `gemini_analysis_model`, `rate_limit_rpm`, `rate_limit_rph`.

---

## ⚠️ Requires manual step — Medium

### 8. `coach-uploads` storage bucket — set `public: false`

The bucket was created with `public: true`, which bypasses RLS for direct URL reads.
Run this migration against your **hosted** Supabase project:

```sql
-- New migration: supabase/migrations/<timestamp>_coach_uploads_private.sql
UPDATE storage.buckets SET public = false WHERE id = 'coach-uploads';
```

After this, the mobile client must use a signed URL to display uploaded images:
```typescript
const { data } = await supabase.storage
  .from('coach-uploads')
  .createSignedUrl(objectPath, 3600); // 1-hour expiry
```

---

## ⚠️ Requires manual step — Low

### 9. iOS auth token storage — use Capacitor Preferences

Supabase defaults to `localStorage` in WebView contexts. On iOS this is unencrypted.
Use the Capacitor Preferences plugin (backed by the iOS Keychain) instead.

```bash
pnpm add @capacitor/preferences
```

```typescript
// mobile/src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js';
import { Preferences } from '@capacitor/preferences';

const supabaseUrl  = import.meta.env.VITE_SUPABASE_URL  || 'https://placeholder.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY
  || import.meta.env.VITE_SUPABASE_KEY
  || 'placeholder-key';

const capacitorStorage = {
  getItem:    (key: string) => Preferences.get({ key }).then(r => r.value),
  setItem:    (key: string, value: string) => Preferences.set({ key, value }).then(() => {}),
  removeItem: (key: string) => Preferences.remove({ key }).then(() => {}),
};

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: { storage: capacitorStorage, persistSession: true, autoRefreshToken: true },
});
```

---

## Summary

| # | Status | Severity | What was done |
|---|--------|----------|---------------|
| 1 | ✅ Done | Critical | Restored WHOOP + Garmin webhook signature verification; noted Strava limitation |
| 2 | ✅ Done | High | Removed `user_metadata` tier fallback — reads `app_metadata` only |
| 3 | ✅ Done | High | Removed `user_metadata` model fallback — reads `app_metadata` only |
| 4 | ✅ Done | High | OAuth authorize endpoints now require a valid JWT |
| 5 | ✅ Done | High | `web_return` validated against `_ALLOWED_RETURN_HOSTS` allowlist |
| 6 | ✅ Done | Medium | CORS wildcard replaced with explicit origin list |
| 7 | ✅ Done | Medium | Sliding-window rate limiter wired into all AI coach endpoints |
| 8 | ⚠️ Manual | Medium | Run SQL migration to set `coach-uploads` bucket `public = false` |
| 9 | ⚠️ Manual | Low | Switch Supabase auth storage to Capacitor Preferences (Keychain) |
