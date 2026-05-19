# Security Fixes

Findings from the vibe-security audit. Fix in priority order.

---

## Critical

### 1. Webhook signature verification disabled — `backend/app/routers/sync.py`

**Impact:** Anyone on the internet can POST fake webhook payloads to inject fraudulent workouts, recovery scores, and sleep data into any athlete's profile.

The WHOOP and Garmin handlers check for a signature header then immediately `pass` without verifying it. The Strava POST handler has no verification at all.

**Fix — WHOOP (`sync.py:298-313`):**

```python
# Before
@router.post("/whoop/webhook")
async def whoop_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    signature = request.headers.get("X-WHOOP-Signature")
    if not signature:
        # raise HTTPException(status_code=401, detail="Missing WHOOP signature")
        pass
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(status_code=200)
    # if not whoop.verify_webhook_signature(body, signature):
    #     raise HTTPException(status_code=401, detail="Invalid WHOOP signature")

# After
@router.post("/whoop/webhook")
async def whoop_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(status_code=200)
    signature = request.headers.get("X-WHOOP-Signature")
    if not signature or not whoop.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid or missing WHOOP signature")
```

**Fix — Garmin (`sync.py:245-253`):**

```python
# Before
@router.post("/garmin/webhook")
async def garmin_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    signature = request.headers.get("X-Garmin-Signature")
    if not signature:
        # For local testing, we might want to skip this or use a mock
        pass
    payload = await request.json()

# After
@router.post("/garmin/webhook")
async def garmin_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    body = await request.body()
    signature = request.headers.get("X-Garmin-Signature")
    webhook_secret = settings.GARMIN_WEBHOOK_SECRET
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Garmin webhook secret not configured")
    expected = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or "", expected):
        raise HTTPException(status_code=401, detail="Invalid Garmin signature")
    try:
        payload = json.loads(body)
    except Exception:
        return Response(status_code=400)
```

**Fix — Strava (`sync.py:535-545`):**

Strava sends an `X-Hub-Signature` header (`sha256=<hmac>`). Verify it before processing:

```python
# Before
@router.post("/strava/webhook")
async def strava_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=200)

# After
import hmac, hashlib

@router.post("/strava/webhook")
async def strava_webhook(request: Request, background_tasks: BackgroundTasks, db=Depends(get_admin_db)):
    body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature", "")
    if sig_header.startswith("sha256="):
        expected = "sha256=" + hmac.new(
            settings.STRAVA_WEBHOOK_VERIFY_TOKEN.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=401, detail="Invalid Strava signature")
    try:
        payload = json.loads(body)
    except Exception:
        return Response(status_code=200)
```

---

## High

### 2. Tier check reads from user-controlled `user_metadata` — `backend/app/dependencies.py:91`

**Impact:** Any user can call `supabase.auth.updateUser({ data: { tier: 'premium' } })` from the client SDK and grant themselves premium access to the AI Coach without paying. `user_metadata` is writable by the user; only `app_metadata` requires service_role.

```python
# Before
app_meta = getattr(u, "app_metadata", None) or {}
user_meta = getattr(u, "user_metadata", None) or {}
tier_raw = (app_meta.get("tier") or user_meta.get("tier") or "free")

# After — only trust app_metadata (admin-controlled)
app_meta = getattr(u, "app_metadata", None) or {}
tier_raw = app_meta.get("tier") or "free"
```

### 3. Gemini model overridable via `user_metadata` — `backend/app/dependencies.py:121`

**Impact:** Same root cause as #2. A user can set `user_metadata.gemini_model` to any string and force the backend to use an arbitrary model on every AI call billed to your Gemini API key.

```python
# Before
for raw in (app_meta.get("gemini_model"), user_meta.get("gemini_model")):
    if isinstance(raw, str):
        m = raw.strip()
        if m:
            return m

# After — only read from app_metadata
raw = app_meta.get("gemini_model")
if isinstance(raw, str):
    m = raw.strip()
    if m:
        return m
```

Apply the same fix to `get_current_gemini_analysis_model` (already reads only from `app_meta` — confirm it stays that way).

### 4. OAuth authorize endpoints are unauthenticated (IDOR) — `backend/app/routers/sync.py:573`, `653`

**Impact:** `GET /v1/sync/oauth/whoop/authorize?athlete_id=<uuid>` requires no authentication. An attacker who knows any athlete's UUID can initiate the OAuth flow and link their own WHOOP/Strava account to the victim's profile. The callback writes via `get_admin_db()` (bypasses RLS), so the attacker's data flows into the victim's biometrics via subsequent webhooks.

```python
# Before
@router.get("/oauth/whoop/authorize")
async def whoop_oauth_authorize(athlete_id: str = None, web_return: str = None):
    ...

# After — derive athlete_id from the authenticated user's JWT
@router.get("/oauth/whoop/authorize")
async def whoop_oauth_authorize(
    web_return: str = None,
    athlete_id: str = Depends(get_current_athlete),
):
    ...
```

Apply the same fix to `/oauth/strava/authorize`.

### 5. Open redirect via `web_return` parameter — `backend/app/routers/sync.py:639`, `754`

**Impact:** The `web_return` URL is embedded in the OAuth state and used directly in `RedirectResponse` without validation. An attacker can craft `?web_return=https://attacker.com` to redirect users to a phishing site after completing OAuth.

```python
# Before
if web_return:
    return RedirectResponse(url=f"{web_return}?provider=whoop&status=success")

# After — validate against an allowlist of known origins
from urllib.parse import urlparse

ALLOWED_RETURN_HOSTS = {
    "yourapp.com",
    "localhost",
}

def _safe_web_return(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host in ALLOWED_RETURN_HOSTS or host.endswith(".yourapp.com"):
            return url
    except Exception:
        pass
    return None

# In both whoop_oauth_callback and strava_oauth_callback:
if safe_url := _safe_web_return(web_return):
    return RedirectResponse(url=f"{safe_url}?provider={provider}&status=success")
# else fall through to deep link response
```

---

## Medium

### 6. CORS wildcard with credentials — `backend/app/main.py:11-17`

**Impact:** `allow_origins=["*"]` with `allow_credentials=True` is invalid per the CORS spec. Browsers reject these responses, making credentialed cross-origin requests silently fail in ways that are hard to debug and mask the actual security boundary.

```python
# Before
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# After — enumerate actual origins
ALLOWED_ORIGINS = [
    "https://yourapp.com",
    "capacitor://localhost",   # Capacitor iOS
    "http://localhost",        # Capacitor Android
    "http://localhost:5173",   # local dev
    "http://localhost:4173",   # local preview
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 7. No rate limiting on AI coach endpoints — `backend/app/routers/coach.py`

**Impact:** `/v1/coach/message`, `/v1/coach/stream`, and `/v1/coach/initialize` call the Gemini API on every request with no per-user throttle. A single account (or anyone exploiting issue #2) can exhaust the Gemini API budget.

```bash
pip install slowapi
```

```python
# In main.py — add limiter
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

```python
# In coach.py — apply limits to AI endpoints
from fastapi import Request
from app.main import limiter

@router.post("/message")
@limiter.limit("20/minute;100/hour")
async def chat_with_coach(request: Request, payload: ChatMessage, ...):
    ...

@router.post("/stream")
@limiter.limit("20/minute;100/hour")
async def stream_chat_with_coach(request: Request, payload: ChatMessage, ...):
    ...

@router.post("/initialize")
@limiter.limit("10/minute")
async def initialize_coach(request: Request, ...):
    ...
```

Use a per-user key function instead of IP if you want tighter per-account limits:

```python
def get_athlete_id(request: Request) -> str:
    return request.state.athlete_id  # set this in a middleware after auth

limiter = Limiter(key_func=get_athlete_id)
```

### 8. `coach-uploads` storage bucket is public — `supabase/migrations/20260429000002_coach_chat_history.sql:47`

**Impact:** Public Supabase buckets bypass RLS for object reads. Anyone who discovers a file URL can download it regardless of the per-user SELECT policy. Health-related images uploaded to chat are exposed.

```sql
-- Before
INSERT INTO storage.buckets (id, name, public)
VALUES ('coach-uploads', 'coach-uploads', true)
ON CONFLICT (id) DO NOTHING;

-- After
INSERT INTO storage.buckets (id, name, public)
VALUES ('coach-uploads', 'coach-uploads', false)
ON CONFLICT (id) DO UPDATE SET public = false;
```

Run this as a new migration. The existing per-user SELECT/INSERT/DELETE policies will then correctly enforce access. The mobile client must use a signed URL (via `supabase.storage.from('coach-uploads').createSignedUrl(...)`) to display images instead of the raw public URL.

---

## Low

### 9. Auth tokens stored in WebView localStorage on iOS — `mobile/src/lib/supabase.ts`

**Impact:** Supabase defaults to `localStorage` in browser contexts. In a Capacitor-wrapped iOS app this is the WKWebView's unencrypted storage. On a jailbroken device, tokens are readable. The Capacitor Preferences plugin writes to encrypted platform storage (iOS Keychain / Android Keystore).

```bash
pnpm add @capacitor/preferences
```

```typescript
// mobile/src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js';
import { Preferences } from '@capacitor/preferences';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://placeholder.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || import.meta.env.VITE_SUPABASE_KEY || 'placeholder-key';

const capacitorStorage = {
  getItem:    (key: string) => Preferences.get({ key }).then(r => r.value),
  setItem:    (key: string, value: string) => Preferences.set({ key, value }).then(() => {}),
  removeItem: (key: string) => Preferences.remove({ key }).then(() => {}),
};

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    storage: capacitorStorage,
    persistSession: true,
    autoRefreshToken: true,
  },
});
```

> **Note:** Capacitor Preferences is not available during SSR/server-side rendering. Guard with `if (typeof window !== 'undefined' && Capacitor.isNativePlatform())` if the SvelteKit adapter ever runs server-side code.

---

## Fix Order Summary

| Priority | Issue | File(s) |
|----------|-------|---------|
| 1 — Critical | Restore webhook signature verification (WHOOP, Garmin, Strava) | `sync.py:245-570` |
| 2 — High | Remove `user_metadata` tier fallback | `dependencies.py:91` |
| 3 — High | Remove `user_metadata` model override | `dependencies.py:121` |
| 4 — High | Add auth to OAuth authorize endpoints | `sync.py:573, 653` |
| 5 — High | Validate `web_return` against allowlist | `sync.py:639, 754` |
| 6 — Medium | Replace CORS wildcard with explicit origin list | `main.py:11` |
| 7 — Medium | Add rate limiting to all `/coach/*` AI endpoints | `coach.py`, `main.py` |
| 8 — Medium | Set `coach-uploads` bucket to `public: false` | migration + new migration |
| 9 — Low | Use Capacitor Preferences for Supabase auth storage | `mobile/src/lib/supabase.ts` |
