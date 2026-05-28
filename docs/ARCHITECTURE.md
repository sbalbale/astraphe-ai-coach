# System Architecture

## Overview

ASTRAPHE is a Supabase-backed coaching app with a SvelteKit mobile/web client, a stateless FastAPI backend, a Google GenAI coach layer, Redis-assisted rate limiting/caching, and third-party training data integrations.

```text
SvelteKit SPA / PWA / Capacitor iOS
  Supabase Auth JWT + fetch()
          |
          v
FastAPI backend
  routers: athlete, workouts, activities, biometrics, coach, sync,
           plan, training-plans, analysis, admin, notifications, debug
          |
          +--> Supabase Postgres/Auth/Storage/RLS/pgvector
          +--> Redis rate limits + activity caches
          +--> Google GenAI coach, analysis, embeddings, grounding
          +--> Strava, WHOOP, Garmin, Resend, FCM/VAPID
```

## Runtime Layers

### Mobile/Web Client

The `mobile/` app is a Svelte 5 + SvelteKit 2 single-page app with SSR disabled and static prerendering. It runs as a browser/PWA app and can be wrapped in the current Capacitor iOS scaffold. Android source is not present in this repo.

Responsibilities:

- Authenticate with Supabase and attach access tokens via `mobile/src/lib/apiAuth.ts`.
- Call the FastAPI backend through `mobile/src/lib/api.ts` using browser `fetch`.
- Render dashboards, training, recovery, sleep, strain, plan, chat, profile, notifications, privacy, zones, and auth routes.
- Initialize push notifications after auth/profile loading.
- Provide scaffolded HealthKit/health integration code; current sync sends an empty/mock payload until native data collection is fully wired.

The client does not calculate TSS, CTL, ATL, TSB, recovery, or strain. Those remain server-side.

### FastAPI Backend

The backend entrypoint is `backend/app/main.py`. It registers production-disabled docs, security headers, CORS, GZip, a global IP rate-limit middleware, `/health`, and routers under `/v1`.

Routers:

- `athlete`: profile, state, metrics, zones, onboarding, account deletion.
- `workouts`: completed workout list, ingestion, deletion, TSS calculation.
- `activity_detail`: streams, laps, intervals, zone distribution, Strava rehydration.
- `biometrics`: paginated daily biometrics and ingestion.
- `coach`: conversations, messages, document uploads, JSON and SSE coach replies.
- `sync`: Garmin, WHOOP, Strava OAuth/webhooks/backfills, integration status, reprocessing.
- `plan` and `training-plans`: legacy plan view and CRUD planned workouts.
- `analysis`: cached screen-level AI insights.
- `admin`: app-metadata user configuration.
- `notifications`: push token registration and non-production test send.
- `debug`: development-only connection/RLS diagnostics.

### Data Layer

Supabase is the durable source of truth for auth, relational data, storage, and pgvector. The canonical schema history is in `supabase/migrations/`.

Key tables include:

- `athletes`
- `workouts`
- `biometrics`
- `sleep_periods`
- `tss_history`
- `training_plans`
- `oauth_tokens`
- `coach_conversations`
- `coach_messages`
- `coach_memories`
- `athlete_analyses`
- `activity_streams`
- `activity_laps`
- `push_tokens`

Most athlete-owned tables use RLS predicates that map `athlete_id` to `athletes.user_id = auth.uid()`.

### AI Layer

The coach uses the `google-genai` SDK. Defaults come from `backend/app/config.py`:

- `GEMINI_MODEL=gemma-4-26b-a4b-it`
- `GEMINI_ANALYSIS_MODEL=gemini-flash-lite-latest`
- `GEMINI_EMBEDDING_MODEL=gemini-embedding-001`

Admin overrides for coach/analysis models are stored in `auth.users.app_metadata`. User-editable metadata is not trusted for authorization or model selection.

Coach behavior is prompt-file driven from `backend/app/prompts/coach_behavior.md`. The agent loop supports custom tools, Google Search grounding, document/image context, RAG memories, XML `<response>` extraction, and background memory persistence.

### Redis Layer

Redis is optional but recommended in multi-instance environments. It backs:

- Per-IP sliding-window rate limits.
- Per-athlete AI minute/hour rate limits.
- Activity stream and workout zone caches.

When `REDIS_URL` is not set or Redis is unreachable, the rate limiter falls back to process-local memory.

### Deployment Layer

Current repo automation deploys the backend through GitHub Actions:

1. Build and push `ghcr.io/sbalbale/astraphe-api`.
2. Connect to the Proxmox host through Cloudflare Access SSH.
3. Run `docker compose pull astraphe-api` and `docker compose up -d astraphe-api`.
4. Run migrations on the remote Supabase/Postgres container.

The frontend is deployed to Firebase Hosting via the Firebase hosting workflows. `backend/cloudbuild.yaml` still exists as an alternate/historical Cloud Run pipeline, but it is not the primary workflow in the current repo.

## Data Flows

### Authenticated API Request

```text
SvelteKit route
  -> Supabase session access token
  -> fetch() with Authorization header
  -> FastAPI dependency calls Supabase auth.get_user()
  -> athletes.id lookup by user_id
  -> per-request PostgREST client receives JWT
  -> RLS-scoped database query
```

### Workout Ingestion

```text
Manual/HealthKit/Strava/Garmin/WHOOP input
  -> FastAPI sync or workout route
  -> source normalization and ownership verification
  -> workout row
  -> TSS/HRSS/strain processing
  -> tss_history update
  -> CTL/ATL/TSB recompute
  -> cached analysis invalidation/refetch on next client request
```

### Strava Detail

```text
Strava OAuth/webhook/backfill
  -> owner_id mapped to oauth_tokens/provider metadata
  -> activity detail fetched
  -> workout upsert/merge
  -> streams and laps stored in activity_streams/activity_laps
  -> activity_detail routes expose streams, laps, intervals, and zones
  -> Redis caches high-read activity detail responses when available
```

### AI Coach

```text
Chat screen
  -> POST /v1/coach/message or /v1/coach/stream
  -> tier/model/rate limits from app_metadata
  -> current context from athletes, biometrics, tss_history, workouts, training_plans
  -> relevant coach_memories via pgvector
  -> Gemini/Gemma agent loop with tools and Google Search grounding
  -> XML response extraction
  -> response saved to coach_messages
  -> important memory saved to coach_memories
```

### Screen-Level AI Analysis

```text
Mobile screen
  -> GET /v1/analysis/<type>
  -> context build from current data
  -> SHA-256 fingerprint
  -> athlete_analyses cache lookup
  -> cached result, deterministic fallback, or Gemini analysis call
  -> content/fingerprint/model/cached response
```

## Security Model

- Supabase Auth access tokens are required for protected routes.
- `app_metadata` is the source of truth for tier, admin status, AI model overrides, and rate-limit overrides.
- `user_metadata` is never used for authorization.
- RLS remains enabled on athlete-owned public tables.
- Production disables FastAPI interactive docs.
- Production startup rejects `TEST_ATHLETE_ID`.
- Security headers are added to all responses.
- CORS origins are enumerated in `backend/app/main.py`.
- Push, OAuth, and service-role credentials stay server-side.
- Debug routes are not registered in production.

## Scaling Notes

The backend is stateless. Shared state lives in Supabase and Redis, so multiple API containers can run concurrently. Expensive recalculation and backfill work is currently performed inside API/background tasks; if traffic grows materially, those jobs should move to a dedicated worker queue.
