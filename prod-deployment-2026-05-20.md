# ASTRAPE Production Deployment Guide
**Date:** 2026-05-20
**Stack:** FastAPI (GCP Cloud Run) · SvelteKit SPA (Cloudflare Pages) · Supabase · Google Gemini · Upstash Redis

---

## Table of Contents

1. [Domain Architecture](#1-domain-architecture)
2. [Pre-Deployment Code Changes](#2-pre-deployment-code-changes)
3. [Supabase Production Setup](#3-supabase-production-setup)
4. [Upstash Redis](#4-upstash-redis)
5. [Backend — GCP Cloud Run](#5-backend--gcp-cloud-run)
6. [Frontend — Cloudflare Pages](#6-frontend--cloudflare-pages)
7. [DNS Configuration](#7-dns-configuration)
8. [Production Environment Variables](#8-production-environment-variables)
9. [OAuth App Configuration](#9-oauth-app-configuration)
10. [Webhook Registration](#10-webhook-registration)
11. [Supabase Auth Redirect URLs](#11-supabase-auth-redirect-urls)
12. [Post-Deployment Verification Checklist](#12-post-deployment-verification-checklist)
13. [Monitoring and Alerting](#13-monitoring-and-alerting)

---

## 1. Domain Architecture

| Subdomain | Purpose | Host |
|---|---|---|
| `astrapeai.com` | **Existing waitlist/marketing site — do not touch** | Wherever it currently lives |
| `app.astrapeai.com` | SvelteKit web app (SPA) | Cloudflare Pages |
| `api.astrapeai.com` | FastAPI backend | GCP Cloud Run |

**Why this split:**

- `astrapeai.com` already serves your waitlist — adding subdomains has zero impact on it. DNS records for `app.` and `api.` are additive only.
- `api.` is a stable contract for every third-party integration (WHOOP, Strava, Garmin) and the mobile app — it never moves regardless of what happens to the frontend.
- `app.` decouples the SvelteKit SPA from the API so each can be deployed, rolled back, and CDN-cached independently.
- Webhook endpoints live at `api.astrapeai.com/v1/sync/<provider>/webhook` — no separate `webhooks.` subdomain needed.

**Optional future subdomains to consider:**
- `status.astrapeai.com` — uptime status page (Instatus or Better Uptime, both have free tiers)
- `docs.astrapeai.com` — redirect to `api.astrapeai.com/docs` (FastAPI auto-generates interactive Swagger docs)

---

## 2. Pre-Deployment Code Changes

These must be merged **before** pushing to production. They fix hardcoded dev values and close security gaps found during codebase review.

### 2a. Update CORS allowed origins — `backend/app/main.py`

The current `ALLOWED_ORIGINS` list references `https://astrape.app`, which is not your production domain. Replace it:

```python
ALLOWED_ORIGINS = [
    "https://app.astrapeai.com",
    "capacitor://localhost",   # Capacitor iOS webview
    "http://localhost",        # Capacitor Android webview
    "http://localhost:5173",   # local dev (vite)
    "http://localhost:4173",   # local preview
    "http://127.0.0.1:5173",
]
```

### 2b. Update OAuth redirect allowlist — `backend/app/routers/sync.py`

`_ALLOWED_RETURN_HOSTS` and the `.endswith()` check both reference `astrape.app`. Update to `astrapeai.com`:

```python
_ALLOWED_RETURN_HOSTS: frozenset[str] = frozenset({
    "astrapeai.com",
    "app.astrapeai.com",
    "localhost",
    "127.0.0.1",
})

def _safe_web_return(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        if host in _ALLOWED_RETURN_HOSTS or host.endswith(".astrapeai.com"):
            return url
    except Exception:
        pass
    return None
```

### 2c. Guard the debug router in production — `backend/app/main.py`

Wrap the debug router include so it is never registered in production:

```python
if settings.APP_ENV != "production":
    app.include_router(debug.router)
```

### 2d. Confirm critical production flags

These must be set correctly in the production environment (checked in section 8):

| Setting | Production value | Why |
|---|---|---|
| `APP_ENV` | `production` | Activates startup validators |
| `WHOOP_WEBHOOK_SKIP_SIG_CHECK` | `false` | Enforces HMAC signature verification on incoming webhooks |
| `WHOOP_WEBHOOK_LOG_RAW` | `false` | Avoids flooding Cloud Run logs with raw payloads |
| `TEST_ATHLETE_ID` | *absent* | Startup validator in `main.py` crashes the server if this is set with `APP_ENV=production` |

### 2e. WHOOP webhook secret — set it equal to the client secret (this is correct)

WHOOP signs webhook payloads using HMAC-SHA256 with your **OAuth client secret** as the key. There is no separate webhook signing secret from the WHOOP portal — your `WHOOP_WEBHOOK_SECRET` must be the same value as `WHOOP_CLIENT_SECRET`. The incorrect startup warning in `main.py` that flagged them as identical has been removed as part of these pre-deployment changes.

---

## 3. Supabase Production Setup

Your local Supabase instance (`127.0.0.1:57321`) is for development only. Production needs a dedicated cloud project.

### 3a. Create a new Supabase project

1. Go to [supabase.com](https://supabase.com) → New Project
2. Name: `astrape-prod`
3. Region: `us-east-1` (closest available to GCP `us-central1`)
4. Set a strong database password — save it in a password manager, you will rarely need it directly
5. Wait ~2 minutes for initialization

### 3b. Push your local schema to production

```powershell
# Install the Supabase CLI if not installed
npm install -g supabase

# Link to the new production project
# Your project ref is in the URL: supabase.com/dashboard/project/<ref>
supabase link --project-ref YOUR_PROJECT_REF

# Option A: if you have a supabase/migrations folder
supabase db push

# Option B: if schema exists only in the local instance, dump it first
supabase db diff --schema public > supabase/migrations/20260520_initial.sql
supabase db push
```

### 3c. Collect production credentials

From Supabase dashboard → Project Settings → API:

| Variable | Where to find it |
|---|---|
| `SUPABASE_URL` | Project URL — looks like `https://xyzxyzxyz.supabase.co` |
| `SUPABASE_KEY` | `anon` `public` key |
| `SUPABASE_SERVICE_ROLE_KEY` | `service_role` key — never expose this to a browser |

### 3d. Verify Row Level Security on all tables

Run in the Supabase SQL Editor:

```sql
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

Any table where `rowsecurity = false` is a potential data exposure risk. Enable with:

```sql
ALTER TABLE your_table_name ENABLE ROW LEVEL SECURITY;
```

Then confirm you have RLS policies in place for each table. With no policies, an RLS-enabled table blocks all access by default — which may be correct for admin-only tables but will break athlete-facing queries if policies are missing.

### 3e. Create the coach-uploads storage bucket

Your code in `api.ts` references a `coach-uploads` bucket. Create it in Supabase → Storage → New Bucket:

- **Name:** `coach-uploads`
- **Public:** Yes (coach image URLs must be publicly readable)
- **File size limit:** 10 MB
- **Allowed MIME types:** `image/jpeg, image/png, image/webp, image/gif, image/heic`

Add storage RLS policies in the SQL Editor:

```sql
-- Athletes can only upload to their own folder (path: coach/<user_id>/...)
CREATE POLICY "Users upload to their own folder" ON storage.objects
FOR INSERT TO authenticated
WITH CHECK (
  bucket_id = 'coach-uploads'
  AND (storage.foldername(name))[2] = auth.uid()::text
);

-- Public read so image URLs work without authentication
CREATE POLICY "Public read coach uploads" ON storage.objects
FOR SELECT USING (bucket_id = 'coach-uploads');
```

### 3f. Configure Supabase email provider (Resend)

By default Supabase uses its own email service with low rate limits. Since you have Resend configured, connect it:

1. Supabase Dashboard → Project Settings → Auth → SMTP Settings
2. Enable custom SMTP
3. Host: `smtp.resend.com`, Port: `465`, User: `resend`, Password: your Resend API key
4. Sender email: something like `noreply@astrapeai.com` (requires a verified Resend domain)

---

## 4. Upstash Redis

Your rate limiter gracefully falls back to in-memory when `REDIS_URL` is unset, but in production you must use real Redis — otherwise per-IP limits are not enforced correctly across multiple Cloud Run instances.

1. Go to [upstash.com](https://upstash.com) → Create Database
2. **Name:** `astrape-prod`
3. **Region:** `us-central1` (matches Cloud Run region)
4. **Type:** Regional (free tier is sufficient to start)
5. After creation, click the database → Details tab → copy the `REDIS_URL`

The URL format is:
```
rediss://default:YOUR_TOKEN@YOUR_HOST.upstash.io:6380
```

The `rediss://` scheme (double `s`) uses TLS automatically — no additional configuration needed.

---

## 5. Backend — GCP Cloud Run

### 5a. Enable required GCP APIs

Run once for the project:

```powershell
gcloud config set project astrape-ai-coach

gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### 5b. Store secrets in GCP Secret Manager

Store all sensitive values in Secret Manager. This allows secret rotation without redeployment and provides a full audit trail.

```bash
# Run once per secret — paste the real value when prompted
for SECRET in \
  SUPABASE_SERVICE_ROLE_KEY \
  GEMINI_API_KEY \
  REDIS_URL \
  WHOOP_CLIENT_SECRET \
  WHOOP_WEBHOOK_SECRET \
  STRAVA_CLIENT_SECRET \
  RESEND_API_KEY \
  VAPID_PRIVATE_KEY
do
  printf "Enter value for %s: " "$SECRET"
  read -rs VALUE
  echo
  printf '%s' "$VALUE" | gcloud secrets create "$SECRET" --data-file=-
done
```

Grant the Cloud Run default service account access:

```bash
SA=$(gcloud iam service-accounts list \
  --filter="displayName~Compute Engine" \
  --format="value(email)" | head -1)

gcloud projects add-iam-policy-binding astrape-ai-coach \
  --member="serviceAccount:$SA" \
  --role="roles/secretmanager.secretAccessor"
```

### 5c. Update `backend/cloudbuild.yaml`

The current file is minimal and does not wire up env vars. Replace it entirely:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - build
      - -t
      - gcr.io/$PROJECT_ID/astrape-api:$COMMIT_SHA
      - -t
      - gcr.io/$PROJECT_ID/astrape-api:latest
      - .
    dir: backend

  - name: 'gcr.io/cloud-builders/docker'
    args: [push, --all-tags, gcr.io/$PROJECT_ID/astrape-api]

  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - astrape-api
      - --image=gcr.io/$PROJECT_ID/astrape-api:$COMMIT_SHA
      - --region=us-central1
      - --allow-unauthenticated
      - --min-instances=0
      - --max-instances=10
      - --memory=512Mi
      - --cpu=1
      - --set-secrets=SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,REDIS_URL=REDIS_URL:latest,WHOOP_CLIENT_SECRET=WHOOP_CLIENT_SECRET:latest,WHOOP_WEBHOOK_SECRET=WHOOP_WEBHOOK_SECRET:latest,STRAVA_CLIENT_SECRET=STRAVA_CLIENT_SECRET:latest,RESEND_API_KEY=RESEND_API_KEY:latest,VAPID_PRIVATE_KEY=VAPID_PRIVATE_KEY:latest
      - --set-env-vars=APP_ENV=production,APP_BASE_URL=https://api.astrapeai.com,SUPABASE_URL=https://YOUR_REF.supabase.co,SUPABASE_KEY=YOUR_ANON_KEY,GCP_PROJECT_ID=astrape-ai-coach,GCP_BUCKET_NAME=astrape-workout-files-bucket,WHOOP_CLIENT_ID=ffe39843-d11d-4f54-a828-44dfbcbd1128,WHOOP_WEBHOOK_SKIP_SIG_CHECK=false,STRAVA_CLIENT_ID=238216,STRAVA_WEBHOOK_VERIFY_TOKEN=YOUR_VERIFY_TOKEN,STRAVA_WEBHOOK_SUBSCRIPTION_ID=0,IP_RATE_LIMIT_RPM=100,VAPID_SUBJECT=mailto:sean.balbale@gmail.com,RESEND_AUDIENCE_ID=bc1ae29b-dec7-43d7-8d4d-8a9f70864d93

images:
  - gcr.io/$PROJECT_ID/astrape-api:$COMMIT_SHA
  - gcr.io/$PROJECT_ID/astrape-api:latest
```

**Rule of thumb:** Non-secret values (anon keys, client IDs, feature flags, URLs) go in `--set-env-vars`. Anything you would rotate or that provides privileged access goes in `--set-secrets`.

### 5d. Set up Cloud Build trigger for CI/CD

1. GCP Console → Cloud Build → Triggers → Create Trigger
2. **Event:** Push to branch `main`
3. **Source:** Connect your GitHub repository
4. **Configuration:** Cloud Build configuration file at `/backend/cloudbuild.yaml`
5. `$PROJECT_ID` and `$COMMIT_SHA` are injected automatically — no substitution variables to configure

### 5e. Bootstrap — first manual deploy

Before the trigger exists, build and deploy manually to verify the pipeline:

```powershell
cd C:\Users\seanb\Documents\astrape-ai-coach\backend
gcloud builds submit --config cloudbuild.yaml .
```

### 5f. Map the custom domain to Cloud Run

After the first successful deployment, map `api.astrapeai.com`:

```powershell
gcloud beta run domain-mappings create `
  --service=astrape-api `
  --domain=api.astrapeai.com `
  --region=us-central1
```

The command outputs A/AAAA DNS records to add to your DNS provider. GCP handles TLS provisioning via Let's Encrypt automatically — the cert becomes active within 24 hours of DNS propagation.

---

## 6. Frontend — Cloudflare Pages

Your SvelteKit app uses `adapter-static` (confirmed in `svelte.config.js`) and outputs a static SPA to `build/`. Cloudflare Pages provides a global CDN, free custom domain SSL, and automatic GitHub-triggered deploys.

### 6a. Create the Pages project

1. [cloudflare.com](https://cloudflare.com) → Pages → Create a Project → Connect to Git
2. Select your GitHub repository
3. Build settings:
   - **Root directory:** `mobile`
   - **Build command:** `pnpm build`
   - **Build output directory:** `build`

### 6b. Set production environment variables

Pages → Settings → Environment Variables → Production:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://api.astrapeai.com` |
| `VITE_SUPABASE_URL` | `https://YOUR_REF.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Your Supabase anon key |
| `VITE_SUPABASE_KEY` | Same as anon key (your `supabase.ts` reads both as a fallback) |
| `NODE_VERSION` | `20` |

> The anon key is intentionally public — it is safe in the browser. Never put `SUPABASE_SERVICE_ROLE_KEY` here.

### 6c. Add the custom domain

Pages → Custom Domains → Add Custom Domain → `app.astrapeai.com`

If `astrapeai.com` nameservers are already on Cloudflare, the DNS record is created automatically. Otherwise Cloudflare gives you a CNAME to add at your registrar.

### 6d. SPA routing

`svelte.config.js` already sets `fallback: 'index.html'`. Cloudflare Pages serves `index.html` for all unmatched paths on SPAs — no `_redirects` file or additional configuration needed.

### 6e. Set a deploy hook (optional, for non-git deploys)

Pages → Settings → Builds & deployments → Add deploy hook → copy the URL. Useful if you ever need to trigger a deploy without a git push.

---

## 7. DNS Configuration

`astrapeai.com` is already live and serving your waitlist — **do not touch the root domain or `www` records.** You only need to add two new subdomain records. Do this at whatever DNS provider currently manages `astrapeai.com` (check your registrar or look up the current nameservers).

### DNS records to add

| Type | Name | Value | Proxy / TTL |
|---|---|---|---|
| CNAME | `app` | `your-project.pages.dev` | Proxied if on Cloudflare, otherwise TTL 300 |
| A | `api` | *IP(s) from GCP `domain-mappings create` output* | **DNS Only / no proxy** |

**Critical for `api.`:** It must resolve directly — do not proxy it through Cloudflare. GCP Cloud Run provisions its own TLS certificate via Let's Encrypt and requires a clean A record. Proxying through Cloudflare breaks cert provisioning.

### If your DNS is already on Cloudflare

Just add the two records above. No other changes. The existing `astrapeai.com` and `www` records stay exactly as they are.

### If your DNS is at a registrar (not Cloudflare)

Add the two CNAME/A records through your registrar's DNS management panel. You do **not** need to move nameservers to Cloudflare — Cloudflare Pages works with a CNAME at any registrar.

### Verify propagation

```powershell
Resolve-DnsName api.astrapeai.com
Resolve-DnsName app.astrapeai.com
```

Allow 24–48 hours for global propagation. [dnschecker.org](https://dnschecker.org) shows per-region status.

---

## 8. Production Environment Variables

Full reference template. **Never commit this file with real values.** All secrets go into GCP Secret Manager and are injected by Cloud Run via `--set-secrets`. Non-sensitive values go in `--set-env-vars` in `cloudbuild.yaml`.

```
# App
APP_NAME=ASTRAPE AI Coach
APP_ENV=production
PORT=8000
APP_BASE_URL=https://api.astrapeai.com
API_PREFIX=/v1
MOBILE_DEEP_LINK_SCHEME=astrape

# Supabase — production project
SUPABASE_URL=https://YOUR_REF.supabase.co
SUPABASE_KEY=YOUR_ANON_KEY                         (env var — anon key is safe as non-secret)
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY    (Secret Manager)

# Google Gemini
GEMINI_API_KEY=YOUR_PROD_GEMINI_KEY                (Secret Manager)
GEMINI_MODEL=gemini-flash-lite-latest
GEMINI_ANALYSIS_MODEL=gemini-flash-lite-latest
GEMINI_EMBEDDING_MODEL=gemini-embedding-001

# GCP
GCP_PROJECT_ID=astrape-ai-coach
GCP_BUCKET_NAME=astrape-workout-files-bucket

# WHOOP
WHOOP_CLIENT_ID=ffe39843-d11d-4f54-a828-44dfbcbd1128
WHOOP_CLIENT_SECRET=YOUR_WHOOP_CLIENT_SECRET       (Secret Manager)
WHOOP_WEBHOOK_SECRET=SAME_AS_CLIENT_SECRET         (Secret Manager — must equal CLIENT_SECRET; WHOOP uses it as the HMAC key)
WHOOP_API_BASE=https://api.prod.whoop.com/developer/v1
WHOOP_OAUTH_AUTH_URL=https://api.prod.whoop.com/oauth/oauth2/auth
WHOOP_OAUTH_TOKEN_URL=https://api.prod.whoop.com/oauth/oauth2/token
WHOOP_WEBHOOK_SKIP_SIG_CHECK=false                 (MUST be false — dev .env has this as true)
WHOOP_WEBHOOK_LOG_RAW=false

# Strava
STRAVA_CLIENT_ID=238216
STRAVA_CLIENT_SECRET=YOUR_STRAVA_CLIENT_SECRET     (Secret Manager)
STRAVA_WEBHOOK_VERIFY_TOKEN=YOUR_VERIFY_TOKEN
STRAVA_WEBHOOK_SUBSCRIPTION_ID=0                   (update after re-registering webhook in section 10)

# Garmin
GARMIN_CONSUMER_KEY=YOUR_GARMIN_KEY
GARMIN_CONSUMER_SECRET=YOUR_GARMIN_SECRET          (Secret Manager)
GARMIN_WEBHOOK_SECRET=YOUR_GARMIN_WEBHOOK_SECRET   (Secret Manager)

# Resend
RESEND_API_KEY=YOUR_RESEND_KEY                     (Secret Manager)
RESEND_AUDIENCE_ID=bc1ae29b-dec7-43d7-8d4d-8a9f70864d93

# Redis (Upstash)
REDIS_URL=rediss://default:TOKEN@HOST.upstash.io:6380  (Secret Manager)

# Rate limiting
IP_RATE_LIMIT_RPM=100

# Push notifications
VAPID_PUBLIC_KEY=YOUR_VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY=YOUR_VAPID_PRIVATE_KEY           (Secret Manager)
VAPID_SUBJECT=mailto:sean.balbale@gmail.com
# FCM_SERVICE_ACCOUNT_JSON=                        (Secret Manager — add when Firebase is ready)

# Must NOT be present in production:
# TEST_ATHLETE_ID   <-- startup validator in main.py crashes the server if this is set
```

---

## 9. OAuth App Configuration

Register production redirect URIs in each provider's portal **before** testing any OAuth flows. If you test before this step, the OAuth callback will be rejected.

### WHOOP — [developer.whoop.com](https://developer.whoop.com)

1. Open your app → Redirect URIs → Add:
   ```
   https://api.astrapeai.com/v1/sync/oauth/whoop/callback
   ```
2. Set `WHOOP_WEBHOOK_SECRET` to the **same value** as `WHOOP_CLIENT_SECRET`. WHOOP uses your client secret as the HMAC-SHA256 signing key for all webhook payloads — there is no separate webhook secret from the portal. With `WHOOP_WEBHOOK_SKIP_SIG_CHECK=false`, your server will verify each incoming webhook using this key.

### Strava — [strava.com/settings/api](https://www.strava.com/settings/api)

1. Update **Authorization Callback Domain** to: `api.astrapeai.com`  
   Strava validates only the domain, not the full path, so you only need to set this once.
2. The full callback URL used in your code is:
   ```
   https://api.astrapeai.com/v1/sync/oauth/strava/callback
   ```

### Garmin — Garmin Health API portal

Update the callback URL to:
```
https://api.astrapeai.com/v1/sync/oauth/garmin/callback
```

---

## 10. Webhook Registration

Webhooks must be re-registered to point to the production API. Complete this **after** `api.astrapeai.com` is live and returning `200` on the health check.

### WHOOP Webhook

In the WHOOP developer portal → Webhooks:
1. Set the webhook URL to: `https://api.astrapeai.com/v1/sync/whoop/webhook`
2. The portal pings the URL immediately — your API must be live first
3. No separate signing secret to copy — WHOOP signs payloads with your OAuth client secret. `WHOOP_WEBHOOK_SECRET` in Secret Manager should already equal `WHOOP_CLIENT_SECRET`.

### Strava Webhook

Strava webhooks are registered via API call. The current dev subscription (ID 345477) must be deleted and re-registered pointing to production. Run these from your local terminal (not the server):

```bash
CLIENT_ID="238216"
CLIENT_SECRET="YOUR_STRAVA_CLIENT_SECRET"
VERIFY_TOKEN="YOUR_STRAVA_VERIFY_TOKEN"

# Check existing subscription
curl -G "https://www.strava.com/api/v3/push_subscriptions" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET"

# Delete the dev subscription
curl -X DELETE \
  "https://www.strava.com/api/v3/push_subscriptions/345477?client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET"

# Register production subscription
curl -X POST "https://www.strava.com/api/v3/push_subscriptions" \
  -F "client_id=$CLIENT_ID" \
  -F "client_secret=$CLIENT_SECRET" \
  -F "callback_url=https://api.astrapeai.com/v1/sync/strava/webhook" \
  -F "verify_token=$VERIFY_TOKEN"
# Response includes "id" — update STRAVA_WEBHOOK_SUBSCRIPTION_ID in Cloud Run env vars
```

Strava sends a GET `hub.challenge` request to your callback URL. The `strava_webhook_verify` handler in `sync.py` responds automatically. On success, Strava returns a `subscription_id` — update `STRAVA_WEBHOOK_SUBSCRIPTION_ID` in your Cloud Run env vars.

### Garmin Webhook

Register in the Garmin Health API developer portal:
- **Webhook URL:** `https://api.astrapeai.com/v1/sync/garmin/webhook`

---

## 11. Supabase Auth Redirect URLs

Supabase validates redirect URLs on every auth operation to prevent open redirect attacks. Configure before testing any auth flows.

1. Supabase Dashboard → Authentication → URL Configuration
2. **Site URL:** `https://app.astrapeai.com`
3. **Redirect URLs** — add all of the following:
   ```
   https://app.astrapeai.com/auth/callback
   https://app.astrapeai.com/auth/reset-password
   astrape://auth/callback
   astrape://auth/reset-password
   http://localhost:5173/auth/callback
   http://localhost:5173/auth/reset-password
   ```
   The `astrape://` entries are for your Capacitor mobile app (the deep link scheme is set in `capacitor.config.ts` as `com.astrape.coach` and the scheme `astrape` is in your `MOBILE_DEEP_LINK_SCHEME` setting). The `redirectUrl.ts` utility already handles selecting the correct URL based on whether the app is running natively or in a web browser.

4. **Email Templates** — update the Confirm Signup and Reset Password templates to use `https://app.astrapeai.com` in any redirect links. Check for any hardcoded localhost URLs in the default templates.

---

## 12. Post-Deployment Verification Checklist

Work through these in order. Do not skip ahead — later steps depend on earlier ones passing.

### Step 1: Backend health check

```bash
curl https://api.astrapeai.com/health
```

Expected response:
```json
{ "status": "healthy", "service": "ASTRAPE API", "redis": "connected" }
```

If `redis` shows `unavailable`: confirm `REDIS_URL` is in Cloud Run env vars and the Upstash instance is active (Upstash dashboard → your database → should show "Active").

### Step 2: TLS and security headers

```powershell
curl.exe -I https://api.astrapeai.com/health
```

Must see all of these response headers:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`

### Step 3: CORS from production origin

```powershell
curl.exe -I -H "Origin: https://app.astrapeai.com" https://api.astrapeai.com/health
```

Must see: `Access-Control-Allow-Origin: https://app.astrapeai.com`

### Step 4: Frontend loads cleanly

- Open `https://app.astrapeai.com` in a browser
- DevTools → Network tab: no requests should be hitting `localhost` or `127.0.0.1`
- DevTools → Console: confirm `[API] Initialized with API_URL: https://api.astrapeai.com` (logged by `api.ts` line 9)

### Step 5: Auth flow end-to-end

1. Sign up with a new test email address
2. Confirm the verification email arrives via Resend
3. Click the email link — must redirect to `https://app.astrapeai.com/auth/callback`
4. Complete onboarding and reach the dashboard
5. Sign out, then sign back in
6. Test forgot password: request reset → receive email → click link → arrives at `/auth/reset-password` → set new password → sign in with new password

### Step 6: Backend reads Supabase

Get a JWT by signing in from the frontend (DevTools → Application → Local Storage → look for the Supabase token), then:

```bash
JWT="PASTE_YOUR_JWT_HERE"
curl -H "Authorization: Bearer $JWT" https://api.astrapeai.com/v1/athlete/profile
```

Expected: athlete profile JSON. If you get `401`: JWT is invalid or Supabase URL/key mismatch. If you get `500`: check Cloud Run logs for a Python traceback.

### Step 7: Rate limiter fires correctly

```bash
JWT="YOUR_JWT"
# Health is exempt from rate limiting (by design in main.py) — test a real endpoint
for i in $(seq 1 110); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $JWT" \
    https://api.astrapeai.com/v1/athlete/state)
  echo "$i: $STATUS"
done
# First 100: 200, request 101+: 429 with Retry-After header
```

### Step 8: Webhook delivery

Trigger a test event from each provider's developer portal dashboard. Then in GCP Console → Cloud Run → `astrape-api` → Logs, filter for:
- `[whoop.webhook]` — WHOOP delivery confirmed
- `[strava.webhook]` — Strava delivery confirmed

### Step 9: OAuth connection flows

1. In the app, navigate to Profile → Connections
2. Tap "Connect WHOOP" → authorize in the WHOOP web view → confirm the callback lands on `https://api.astrapeai.com/v1/sync/oauth/whoop/callback` → app returns to Connections showing "Connected"
3. Repeat for Strava
4. Check Supabase → Table Editor → `oauth_tokens` — rows must exist for the test user with `provider = 'whoop'` and `provider = 'strava'`

### Step 10: Debug router is blocked

```powershell
curl.exe -s -o NUL -w "%{http_code}" https://api.astrapeai.com/debug
# Expected: 404
```

### Step 11: Startup validator confirmed clean

If Steps 1–10 all pass, the startup validator in `main.py` confirmed that `TEST_ATHLETE_ID` is absent (it crashes the server at boot if present when `APP_ENV=production`).

---

## 13. Monitoring and Alerting

### GCP Cloud Run alerting policies

GCP Console → Cloud Monitoring → Alerting → Create Policy:

**5xx error rate policy:**
- Metric: `run.googleapis.com/request_count` filtered by `response_code_class = 5xx`
- Condition: ratio exceeds 5% of total requests over a 5-minute window
- Notification: email to `sean.balbale@gmail.com`

**High latency policy:**
- Metric: `run.googleapis.com/request_latencies` (percentile: p99)
- Condition: exceeds 5,000 ms over a 5-minute window

### Uptime check

GCP Console → Cloud Monitoring → Uptime Checks → Create:
- **Target:** `https://api.astrapeai.com/health`
- **Check period:** 1 minute
- **Alert:** if the check fails 2 consecutive times

Cloudflare provides automatic uptime monitoring and alerting for the `app.` frontend under Analytics → Web Analytics — no additional setup needed.

### Cloud Logging queries

Useful queries in GCP Log Explorer:

```
# All WHOOP webhook deliveries
resource.type="cloud_run_revision"
textPayload=~"\[whoop\.webhook\]"

# Strava webhook deliveries
resource.type="cloud_run_revision"
textPayload=~"\[strava\.webhook\]"

# 5xx errors only
resource.type="cloud_run_revision"
httpRequest.status>=500

# Rate limiter blocks (429)
resource.type="cloud_run_revision"
httpRequest.status=429

# OAuth callback events
resource.type="cloud_run_revision"
textPayload=~"oauth\.callback"
```

### Supabase observability

- Dashboard → Database → Reports — query performance and slow query identification
- Dashboard → Auth → Users — track signup rate over time
- Dashboard → Authentication → Rate Limits — configure per-email and per-IP caps for auth endpoints to prevent abuse

---

## Quick Reference: Production URLs and Endpoints

| Resource | URL |
|---|---|
| Web app | `https://app.astrapeai.com` |
| API base | `https://api.astrapeai.com` |
| API interactive docs (Swagger) | `https://api.astrapeai.com/docs` |
| Health check | `https://api.astrapeai.com/health` |
| WHOOP OAuth authorize | `https://api.astrapeai.com/v1/sync/oauth/whoop/authorize` |
| WHOOP OAuth callback | `https://api.astrapeai.com/v1/sync/oauth/whoop/callback` |
| WHOOP webhook | `https://api.astrapeai.com/v1/sync/whoop/webhook` |
| Strava OAuth authorize | `https://api.astrapeai.com/v1/sync/oauth/strava/authorize` |
| Strava OAuth callback | `https://api.astrapeai.com/v1/sync/oauth/strava/callback` |
| Strava webhook | `https://api.astrapeai.com/v1/sync/strava/webhook` |
| Garmin webhook | `https://api.astrapeai.com/v1/sync/garmin/webhook` |
