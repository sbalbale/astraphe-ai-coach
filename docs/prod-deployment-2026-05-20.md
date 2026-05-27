# ASTRAPE Production Deployment Guide

> **Superseded for backend/Redis/DB deploy:** Use [DEPLOYMENT.md](./DEPLOYMENT.md) — self-hosted FastAPI, Supabase, and Redis on Proxmox via GitHub Actions. This document is retained for historical Firebase/Cloud Run/Upstash steps.

**Date:** 2026-05-20
**Stack (historical):** FastAPI (GCP Cloud Run) · SvelteKit SPA (Firebase Hosting) · Supabase · Google Gemini · Upstash Redis · Firebase (FCM for iOS/Android push)

---

## Table of Contents

1. [Domain Architecture](#1-domain-architecture)
2. [Pre-Deployment Code Changes](#2-pre-deployment-code-changes)
3. [Supabase Production Setup](#3-supabase-production-setup) *(includes admin user grant, §3f)*
4. [Upstash Redis](#4-upstash-redis)
5. [Backend — GCP Cloud Run](#5-backend--gcp-cloud-run)
6. [Frontend — Firebase Hosting](#6-frontend--firebase-hosting)
7. [DNS Configuration](#7-dns-configuration)
8. [Production Environment Variables](#8-production-environment-variables)
9. [OAuth App Configuration](#9-oauth-app-configuration)
10. [Webhook Registration](#10-webhook-registration)
11. [Supabase Auth Redirect URLs](#11-supabase-auth-redirect-urls)
12. [Post-Deployment Verification Checklist](#12-post-deployment-verification-checklist)
13. [Monitoring and Alerting](#13-monitoring-and-alerting)

---

## 1. Domain Architecture


| Subdomain           | Purpose                                             | Host                        |
| ------------------- | --------------------------------------------------- | --------------------------- |
| `astrapeai.com`     | **Existing waitlist/marketing site — do not touch** | Wherever it currently lives |
| `app.astrapeai.com` | SvelteKit web app (SPA)                             | Firebase Hosting            |
| `api.astrapeai.com` | FastAPI backend                                     | GCP Cloud Run               |


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


| Setting                        | Production value | Why                                                                                        |
| ------------------------------ | ---------------- | ------------------------------------------------------------------------------------------ |
| `APP_ENV`                      | `production`     | Activates startup validators                                                               |
| `WHOOP_WEBHOOK_SKIP_SIG_CHECK` | `false`          | Enforces HMAC signature verification on incoming webhooks                                  |
| `WHOOP_WEBHOOK_LOG_RAW`        | `false`          | Avoids flooding Cloud Run logs with raw payloads                                           |
| `TEST_ATHLETE_ID`              | *absent*         | Startup validator in `main.py` crashes the server if this is set with `APP_ENV=production` |


**FastAPI interactive docs (`/docs` and `/redoc`):** By default FastAPI serves a public Swagger UI at `https://api.astrapeai.com/docs`. This exposes every endpoint, request/response schema, and authorization flow to anyone. If you want to disable it before go-live, add `docs_url=None, redoc_url=None` to the `FastAPI(...)` constructor in `main.py`. If you keep it open, be aware it is indexed by search engines and exposes your API surface area publicly.

### 2e. WHOOP webhook signature verification

WHOOP does **not** issue a separate webhook signing secret. Verification uses your **OAuth client secret** from the [WHOOP Developer Dashboard](https://developer-dashboard.whoop.com/), per [WHOOP webhooks security](https://developer.whoop.com/docs/developing/webhooks/#webhooks-security).

**Secret Manager / env**


| Variable               | Production value                                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| `WHOOP_CLIENT_SECRET`  | Client secret from the portal (64-char hex string)                                                              |
| `WHOOP_WEBHOOK_SECRET` | Same value as `WHOOP_CLIENT_SECRET`, **or omit** — the server falls back to `WHOOP_CLIENT_SECRET` automatically |


**How the server verifies each POST** (`backend/app/services/whoop.py`):

1. Read raw request body bytes (do not re-serialize JSON).
2. Read headers `X-WHOOP-Signature` and `X-WHOOP-Signature-Timestamp` (milliseconds since epoch).
3. Compute `base64(HMAC-SHA256(timestamp_utf8 + raw_body, client_secret_utf8))`.
4. Compare to `X-WHOOP-Signature` with `hmac.compare_digest`. Mismatch → `401`.

**Important:** The HMAC key is the client secret **as a UTF-8 string** (the literal hex characters from the dashboard). Do **not** `bytes.fromhex()` the secret — that produces the wrong signature and every webhook returns `401`.

**Dev vs prod flags**


| Setting                        | Dev (local)                                                | Production         |
| ------------------------------ | ---------------------------------------------------------- | ------------------ |
| `WHOOP_WEBHOOK_SKIP_SIG_CHECK` | `false` once ngrok + secrets are configured                | `false` (required) |
| `WHOOP_WEBHOOK_LOG_RAW`        | `true` optional — logs `[whoop.webhook.raw]` for debugging | `false`            |


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


| Variable                    | Where to find it                                         |
| --------------------------- | -------------------------------------------------------- |
| `SUPABASE_URL`              | Project URL — looks like `https://xyzxyzxyz.supabase.co` |
| `SUPABASE_KEY`              | `anon` `public` key                                      |
| `SUPABASE_SERVICE_ROLE_KEY` | `service_role` key — never expose this to a browser      |


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

### 3f. Grant admin access to the first user

The backend exposes `/v1/admin/users` endpoints that allow listing users and updating their tier, model overrides, and rate limits. These endpoints require `is_admin: true` in the user's Supabase `app_metadata`. There is no UI for this — you must set it directly via the SQL Editor using the service role.

1. Sign up with your admin email address through the normal auth flow so the user exists in Supabase Auth.
2. Find your `user_id` in Supabase → Authentication → Users.
3. Run in the SQL Editor (Supabase Dashboard → SQL Editor):

```sql
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"is_admin": true, "tier": "premium"}'::jsonb
WHERE id = 'YOUR_USER_ID';
```

1. Sign out and sign back in so the refreshed JWT carries the updated `app_metadata`.
2. Verify: `GET https://api.astrapeai.com/v1/admin/users` with your Bearer token should return a user list, not a `403`.

> **Note:** Only users with `is_admin: true` in `app_metadata` (not `user_metadata`) can call admin endpoints. Users can write their own `user_metadata` via the Supabase client SDK, so the admin check deliberately reads only from `app_metadata`, which requires the service role or a SQL editor change to modify.

### 3g. Configure Supabase email provider (Resend)

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
3. **Region:** `us-east-1` (must match Cloud Run `us-east4` in `backend/cloudbuild.yaml`; cross-region causes Redis timeouts)
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
  GARMIN_CONSUMER_SECRET \
  GARMIN_WEBHOOK_SECRET \
  RESEND_API_KEY \
  VAPID_PRIVATE_KEY \
  FCM_SERVICE_ACCOUNT_JSON
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
      - --set-secrets=SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,REDIS_URL=REDIS_URL:latest,WHOOP_CLIENT_SECRET=WHOOP_CLIENT_SECRET:latest,WHOOP_WEBHOOK_SECRET=WHOOP_WEBHOOK_SECRET:latest,STRAVA_CLIENT_SECRET=STRAVA_CLIENT_SECRET:latest,GARMIN_CONSUMER_SECRET=GARMIN_CONSUMER_SECRET:latest,GARMIN_WEBHOOK_SECRET=GARMIN_WEBHOOK_SECRET:latest,RESEND_API_KEY=RESEND_API_KEY:latest,VAPID_PRIVATE_KEY=VAPID_PRIVATE_KEY:latest,FCM_SERVICE_ACCOUNT_JSON=FCM_SERVICE_ACCOUNT_JSON:latest
      - --set-env-vars=APP_ENV=production,APP_BASE_URL=https://api.astrapeai.com,SUPABASE_URL=https://YOUR_REF.supabase.co,SUPABASE_KEY=YOUR_ANON_KEY,GCP_PROJECT_ID=astrape-ai-coach,GCP_BUCKET_NAME=astrape-workout-files-bucket,WHOOP_CLIENT_ID=ffe39843-d11d-4f54-a828-44dfbcbd1128,WHOOP_WEBHOOK_SKIP_SIG_CHECK=false,STRAVA_CLIENT_ID=238216,STRAVA_WEBHOOK_VERIFY_TOKEN=YOUR_VERIFY_TOKEN,STRAVA_WEBHOOK_SUBSCRIPTION_ID=0,GARMIN_CONSUMER_KEY=YOUR_GARMIN_CONSUMER_KEY,IP_RATE_LIMIT_RPM=100,VAPID_PUBLIC_KEY=YOUR_VAPID_PUBLIC_KEY,VAPID_SUBJECT=mailto:sean.balbale@gmail.com,RESEND_AUDIENCE_ID=bc1ae29b-dec7-43d7-8d4d-8a9f70864d93

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

## 6. Frontend — Firebase Hosting

Your SvelteKit app uses `adapter-static` (`mobile/svelte.config.js`) and outputs a static SPA to `mobile/build/`. **Firebase Hosting** is a good fit here because you are already on GCP for the API and need a **Firebase project for FCM** (iOS/Android push via Capacitor). One Firebase project can cover both the hosted web app and push — see also [docs/PUSH_NOTIFICATIONS.md](docs/PUSH_NOTIFICATIONS.md).

**What Firebase is (and is not) responsible for**


| Concern                        | Service                                                                           |
| ------------------------------ | --------------------------------------------------------------------------------- |
| Web app at `app.astrapeai.com` | Firebase Hosting                                                                  |
| REST API, webhooks, AI coach   | GCP Cloud Run (`api.astrapeai.com`) — unchanged                                   |
| Auth + database                | Supabase — unchanged                                                              |
| iOS/Android push tokens → FCM  | Firebase Cloud Messaging (native app config + backend `FCM_SERVICE_ACCOUNT_JSON`) |
| Browser/PWA push               | VAPID + service worker (not FCM) — backend `VAPID_*` env vars                     |


Hosting the SPA on Firebase is **not** required for App Store push, but using the **same Firebase project** for Hosting + FCM keeps credentials, billing, and console management in one place.

### 6a. Create / link the Firebase project

1. [Firebase Console](https://console.firebase.google.com/) → **Add project** (e.g. `astrape-prod`) or use an existing project.
2. **Link to GCP** (recommended): Project settings → Integrations → link to GCP project `astrape-ai-coach` so Hosting, Cloud Run, and Secret Manager share one billing account.
3. In the same project, register apps you need:
  - **Web** — optional label for Hosting; not required for FCM.
  - **iOS** — bundle ID `com.astrape.coach` → download `GoogleService-Info.plist` → `mobile/ios/App/App/` (see PUSH_NOTIFICATIONS.md).
  - **Android** — package `com.astrape.coach` → `google-services.json` → `mobile/android/app/` when you ship Android.
4. **APNs for iOS push:** Firebase Console → Project settings → Cloud Messaging → Apple app configuration → upload your APNs Authentication Key (.p8) from Apple Developer. Without this, FCM cannot deliver to iOS devices even if the native app registers tokens.
5. **Backend FCM:** Project settings → Service accounts → **Generate new private key** → store JSON in GCP Secret Manager as `FCM_SERVICE_ACCOUNT_JSON` and mount on Cloud Run (§8).

### 6b. Firebase Hosting config (`mobile/`)

From the repo root, add hosting config under `mobile/` (or run `firebase init hosting` there and accept `build` as the public directory):

`**mobile/firebase.json`**

```json
{
  "hosting": {
    "public": "build",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [{ "source": "**", "destination": "/index.html" }]
  }
}
```

`**mobile/.firebaserc**` (replace with your Firebase project ID)

```json
{
  "projects": {
    "default": "astrape-prod"
  }
}
```

`svelte.config.js` already sets `fallback: 'index.html'`; the Hosting rewrite above mirrors that for client-side routes (`/auth/callback`, `/dashboard`, etc.).

### 6c. Production build environment variables

Set these when building (local `.env.production`, CI secrets, or `firebase deploy` pre-build step). They are baked into the static bundle at build time:


| Variable                | Value                                                         |
| ----------------------- | ------------------------------------------------------------- |
| `VITE_API_URL`          | `https://api.astrapeai.com`                                   |
| `VITE_SUPABASE_URL`     | `https://YOUR_REF.supabase.co`                                |
| `VITE_SUPABASE_KEY`     | Supabase anon key (public in browser)                         |
| `VITE_VAPID_PUBLIC_KEY` | Same public key as backend `VAPID_PUBLIC_KEY` (web push only) |


> Never put `SUPABASE_SERVICE_ROLE_KEY` or `FCM_SERVICE_ACCOUNT_JSON` in frontend env vars.

Example local production build:

```bash
cd mobile
pnpm install
# ensure mobile/.env.production or exported vars contain the table above
pnpm build
firebase deploy --only hosting
```

### 6d. Custom domain `app.astrapeai.com`

Firebase Console → Hosting → **Add custom domain** → `app.astrapeai.com`.

Firebase provides DNS records (often a CNAME to `your-project.web.app` plus a TXT for domain verification). Add them at the same DNS provider that manages `astrapeai.com` — **do not change** existing root/`www` waitlist records.

Allow up to 24 hours for TLS provisioning after DNS propagates.

### 6e. Deploy options

**Manual (first deploy):**

```bash
npm install -g firebase-tools
firebase login
cd mobile
pnpm build
firebase deploy --only hosting
```

**CI (GitHub Actions):** Store `FIREBASE_SERVICE_ACCOUNT` JSON as a repo secret (Firebase Console → Project settings → Service accounts → Generate new private key for CI, or use Workload Identity Federation with GCP). Workflow steps: `pnpm build` in `mobile/` → `firebase deploy --only hosting --project astrape-prod`.

**Preview channels (optional):** `firebase hosting:channel:deploy pr-123` for short-lived preview URLs before merging.

### 6f. Native iOS build (App Store / TestFlight)

The Capacitor shell loads the same SvelteKit UI. Push uses **FCM**, not Hosting:

1. Complete §6a (iOS app in Firebase + APNs key + `GoogleService-Info.plist`).
2. Xcode → Push Notifications + Background Modes → Remote notifications.
3. `cd mobile && pnpm build && npx cap sync ios` — point `capacitor.config.ts` server URL at production API or bundled assets for store builds.
4. Archive in Xcode → TestFlight / App Store.

Store builds talk to `https://api.astrapeai.com`; they do not need the Firebase Hosting URL unless you load the web UI from `app.astrapeai.com` inside the WebView.

---

## 7. DNS Configuration

`astrapeai.com` is already live and serving your waitlist — **do not touch the root domain or `www` records.** You only need to add two new subdomain records. Do this at whatever DNS provider currently manages `astrapeai.com` (check your registrar or look up the current nameservers).

### DNS records to add


| Type  | Name  | Value                                                                             | Proxy / TTL                               |
| ----- | ----- | --------------------------------------------------------------------------------- | ----------------------------------------- |
| CNAME | `app` | *Value from Firebase Hosting custom-domain wizard* (often `your-project.web.app`) | TTL 300; follow Firebase console exactly  |
| A     | `api` | *IP(s) from GCP `domain-mappings create` output*                                  | **Direct to GCP — no CDN proxy in front** |


**Critical for `api.`:** Cloud Run domain mapping needs a clean path to Google's load balancer. Do not put `api.` behind a proxy that terminates TLS differently than GCP expects.

**For `app.`:** Use only the records Firebase shows when you add `app.astrapeai.com`. Firebase provisions its own CDN and TLS for Hosting.

### Registrar vs Cloudflare DNS

Add the `app` and `api` records at whatever currently hosts DNS for `astrapeai.com`. You do **not** need to move the root domain or waitlist site. Existing `astrapeai.com` / `www` records stay unchanged.

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
GEMINI_MODEL=gemma-4-26b-a4b-it
GEMINI_ANALYSIS_MODEL=gemini-3-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-2

# GCP
GCP_PROJECT_ID=astrape-ai-coach
GCP_BUCKET_NAME=astrape-workout-files-bucket

# WHOOP
WHOOP_CLIENT_ID=ffe39843-d11d-4f54-a828-44dfbcbd1128
WHOOP_CLIENT_SECRET=YOUR_WHOOP_CLIENT_SECRET       (Secret Manager)
WHOOP_WEBHOOK_SECRET=SAME_AS_CLIENT_SECRET         (Secret Manager — optional duplicate of CLIENT_SECRET; UTF-8 HMAC key, not hex-decoded)
WHOOP_API_BASE=https://api.prod.whoop.com/developer/v1
WHOOP_OAUTH_AUTH_URL=https://api.prod.whoop.com/oauth/oauth2/auth
WHOOP_OAUTH_TOKEN_URL=https://api.prod.whoop.com/oauth/oauth2/token
WHOOP_WEBHOOK_SKIP_SIG_CHECK=false                 (MUST be false in production)
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
FCM_SERVICE_ACCOUNT_JSON={"type":"service_account",...}  (Secret Manager — Firebase §6a; required for iOS/Android push)

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
2. Store `WHOOP_CLIENT_SECRET` in Secret Manager. Set `WHOOP_WEBHOOK_SECRET` to the **same value** (optional if you rely on the code fallback). With `WHOOP_WEBHOOK_SKIP_SIG_CHECK=false`, each webhook is verified using HMAC-SHA256 over `timestamp + raw_body` with the client secret as UTF-8 (see §2e).

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

In the [WHOOP Developer Dashboard](https://developer-dashboard.whoop.com/) → your app → **Webhooks**:

1. Set the webhook URL to: `https://api.astrapeai.com/v1/sync/whoop/webhook`
2. Choose **Model Version v2** if your API integration uses v2 UUID resource IDs (recommended for new work).
3. Save — the portal may ping the URL immediately; the API must be live and return `2XX` with valid signature verification enabled.
4. **Signing:** WHOOP sends `X-WHOOP-Signature` and `X-WHOOP-Signature-Timestamp`. There is no separate webhook secret in the portal — use the same OAuth **client secret** in Secret Manager (see §2e). Ensure `WHOOP_WEBHOOK_SKIP_SIG_CHECK=false` on Cloud Run before go-live.

**Verify delivery (after deploy):** Log a short activity or nudge a sleep in the WHOOP app. In Cloud Run logs you should see `[whoop.webhook] type=workout.updated` (or `sleep.updated` / `recovery.updated`) and **no** `[whoop.sig] MISMATCH`. A `401` on `POST /v1/sync/whoop/webhook` almost always means the secret in Secret Manager does not match the dashboard, or the secret was hex-decoded before HMAC (fixed in code — redeploy required).

### Strava Webhook

Strava webhooks are **not** configured in the Strava website UI. They are **push subscriptions** registered via API, tied to your app’s `callback_url`. WHOOP lets you paste a URL in the dashboard; Strava does not — you must register through the API (or the helper script below).

**Production (register once):** With `api.astrapeai.com` live:

```bash
cd backend
# uvicorn must be running; production URL must answer GET hub.challenge
python scripts/register_strava_webhook.py
```

Set `APP_BASE_URL=https://api.astrapeai.com` in `.env` (or export it) before running the script so it registers the production callback. The script deletes stale subscriptions, registers the URL from `APP_BASE_URL`, and writes `STRAVA_WEBHOOK_SUBSCRIPTION_ID` into `backend/.env`.

**Local dev (re-register whenever ngrok changes):**

1. Start ngrok → copy the new HTTPS URL into `APP_BASE_URL` in `backend/.env`.
2. Start uvicorn (Strava verifies the callback with a GET `hub.challenge` during registration).
3. Run:
  ```bash
   cd backend
   python scripts/register_strava_webhook.py
  ```
4. On backend startup (`APP_ENV=development`), the server prints either `Strava webhook OK` or a **WARNING** with the same fix command if the subscription still points at an old tunnel.

**Optional — stable ngrok hostname:** A reserved ngrok domain (paid) avoids re-registration on every restart. Point it at `:8000`, set `APP_BASE_URL` to that fixed host, and run `register_strava_webhook.py` once.

Strava sends a GET `hub.challenge` during registration; `GET /v1/sync/strava/webhook` in `sync.py` handles it. After registration, activity events POST to the same URL.

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

Trigger a test event from each provider (WHOOP: log a short activity or edit a sleep by 1 minute — see [WHOOP webhooks testing](https://developer.whoop.com/docs/developing/webhooks/#webhooks-testing)). Then in GCP Console → Cloud Run → `astrape-api` → Logs:


| Log pattern                       | Meaning                                                                                                                |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `[whoop.webhook] type=...`        | WHOOP payload accepted and processing started                                                                          |
| `[whoop.sig] MISMATCH`            | Signature failed — check Secret Manager secret matches dashboard; redeploy if on an old build that hex-decoded the key |
| `401` on `/v1/sync/whoop/webhook` | Same as MISMATCH — fix secrets or signature code before go-live                                                        |
| `[strava.webhook]`                | Strava delivery confirmed                                                                                              |


### Step 9: OAuth connection flows

1. In the app, navigate to Profile → Connections
2. Tap "Connect WHOOP" → authorize in the WHOOP web view → confirm the callback lands on `https://api.astrapeai.com/v1/sync/oauth/whoop/callback` → app returns to Connections showing "Connected"
3. Repeat for Strava
4. Check Supabase → Table Editor → `oauth_tokens` — rows must exist for the test user with `provider = 'whoop'` and `provider = 'strava'`

### Step 10: Debug router is blocked

```powershell
curl.exe -s -o NUL -w "%{http_code}" https://api.astrapeai.com/v1/debug/connection
# Expected: 404 (the endpoint checks APP_ENV and refuses to respond outside development)
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

**Frontend uptime:** GCP Monitoring → Uptime check on `https://app.astrapeai.com` (same pattern as API health in §13), or Firebase Hosting status in the console. Optional: Firebase Performance Monitoring for web vitals after you add the web SDK.

### Cloud Logging queries

Useful queries in GCP Log Explorer:

```
# All WHOOP webhook deliveries (success path)
resource.type="cloud_run_revision"
textPayload=~"\[whoop\.webhook\]"

# WHOOP signature failures (should be empty in production)
resource.type="cloud_run_revision"
textPayload=~"\[whoop\.sig\]"

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


| Resource                       | URL                                                        |
| ------------------------------ | ---------------------------------------------------------- |
| Web app                        | `https://app.astrapeai.com`                                |
| API base                       | `https://api.astrapeai.com`                                |
| API interactive docs (Swagger) | `https://api.astrapeai.com/docs`                           |
| Health check                   | `https://api.astrapeai.com/health`                         |
| WHOOP OAuth authorize          | `https://api.astrapeai.com/v1/sync/oauth/whoop/authorize`  |
| WHOOP OAuth callback           | `https://api.astrapeai.com/v1/sync/oauth/whoop/callback`   |
| WHOOP webhook                  | `https://api.astrapeai.com/v1/sync/whoop/webhook`          |
| Strava OAuth authorize         | `https://api.astrapeai.com/v1/sync/oauth/strava/authorize` |
| Strava OAuth callback          | `https://api.astrapeai.com/v1/sync/oauth/strava/callback`  |
| Strava webhook                 | `https://api.astrapeai.com/v1/sync/strava/webhook`         |
| Garmin webhook                 | `https://api.astrapeai.com/v1/sync/garmin/webhook`         |


