# System Architecture

## Overview

ASTRAPHE is a Supabase-backed coaching app with a SvelteKit mobile/web client, a FastAPI backend (no per-request state; runs as several replicas), a Google GenAI coach layer, a Redis layer for rate limits, caches, and cross-replica coordination, and third-party training data integrations.

```text
SvelteKit SPA / PWA / Capacitor iOS
  Supabase Auth JWT + fetch()
          |
          v
FastAPI backend (astraphe-api, 2 replicas in production)
  routers: athlete, workouts, activities, biometrics, weight, coach, sync
           (incl. Garmin connect), plan, training-plans, analysis, admin,
           notifications, messaging, debug (non-production only)
  background loops: WHOOP token refresh, Strava/WHOOP startup backfill,
           Garmin poll, notification scheduler
          |
          +--> Supabase Postgres/Auth/Storage/RLS/pgvector
          +--> Redis: rate limits, response caches, shared locks/quotas
          +--> Google GenAI (or an OpenAI-compatible endpoint): coach,
               analysis, embeddings, grounding
          +--> Strava, WHOOP, Garmin, Intervals.icu, Resend, FCM/VAPID,
               SearXNG (optional), photon-bridge (iMessage)

Claude / any MCP client
  OAuth 2.1 (Supabase Auth as authorization server) + Streamable HTTP
          |
          v
MCP server (mcp-server/) -- separate service, imports backend/app's
  tool handlers directly; RLS-scoped by the caller's own token
          |
          +--> Supabase Postgres/Auth/RLS (same project as the backend)
```

## Runtime Layers

### Mobile/Web Client

The `mobile/` app is a Svelte 5 + SvelteKit 2 single-page app with SSR disabled and static prerendering. It runs as a browser/PWA app and can be wrapped in the Capacitor iOS project (`mobile/ios`). Android source is not present in this repo.

Responsibilities:

- Authenticate with Supabase and attach access tokens via `mobile/src/lib/apiAuth.ts`.
- Call the FastAPI backend through `mobile/src/lib/api.ts` using browser `fetch`.
- Render dashboard, training, trends, recovery, readiness, sleep, strain, heart rate, weight, plan, chat, profile, zones, onboarding, OAuth, and auth routes (`mobile/src/routes/`).
- Initialize push notifications after auth/profile loading.
- Provide scaffolded HealthKit code (`mobile/src/lib/integrations/health.ts`); it posts an empty/mock payload to `/v1/biometrics/sync`, a route the backend doesn't have, so HealthKit data isn't synced yet.

The client does not calculate TSS, CTL, ATL, TSB, recovery, or strain. Those remain server-side.

### FastAPI Backend

The backend entrypoint is `backend/app/main.py`. It registers production-disabled docs, security headers, CORS, GZip, a global IP rate-limit middleware, `/health`, startup background loops, and routers under `/v1`.

Routers:

- `athlete`: profile, state, metrics, zones, onboarding, account deletion.
- `workouts`: completed workout list, ingestion, edit, deletion, TSS calculation, plan link lookup.
- `activity_detail` (`/v1/activities`): streams, laps, intervals, zone distribution, Strava rehydration.
- `biometrics`: paginated daily biometrics, ingestion, and the all-day heart rate day view.
- `weight`: weigh-ins, soft delete/restore, goal weight.
- `coach`: conversations, messages, memories, document uploads, JSON/async/SSE coach replies, reply progress.
- `sync`: WHOOP, Strava, Intervals.icu OAuth/webhooks/backfills, integration status, unlink, reprocessing.
- `garmin_sync` (also under `/v1/sync`): Garmin username/password connect, MFA, backfill.
- `plan` and `training-plans`: legacy plan view, CRUD planned workouts, linking recorded workouts to sessions.
- `analysis`: cached screen-level AI insights.
- `admin`: app-metadata user configuration and maintenance.
- `notifications`: push token registration, test send, device count.
- `messaging`: inbound texts from `photon-bridge` (iMessage coach channel).
- `debug`: development-only connection/RLS diagnostics.

Background loops started at startup (all skipped when `BACKGROUND_LOOPS_ENABLED=false`). Each runs in every replica, so each claims work before doing it:

- `services/token_refresh.py`: refreshes WHOOP tokens near expiry, behind an atomic claim on `oauth_tokens.refresh_lock_expires_at`.
- Strava and WHOOP startup backfills of the last 24 h (`*_STARTUP_BACKFILL_*`).
- `services/garmin.py` `poll_loop`: Garmin has no webhook, so this is the only sync path; one replica per athlete per tick via the same lock column. Each sync also stores the day's all-day heart rate, runs workout auto-detection, and saves weigh-ins.
- `services/notification_scheduler.py`: morning readiness, evening digest, weekly summary, sync problems; every send is claimed in `notification_log`.

Notable services for recent features:

- `services/heart_rate_series.py`: stores and reads all-day heart rate (`heart_rate_series`) and builds the Heart rate screen payload.
- `services/hr_activity_detection.py`: detects workouts from all-day HR (heart-rate-reserve threshold, minimum 10 active minutes) and saves them with source `hr_detected`; deleted detections go to `hr_detection_dismissals`.
- `services/day_strain.py`: day strain from workouts plus all-day HR minutes outside workouts.
- `services/weight.py`: weigh-ins and the daily `biometrics.weight_kg` they feed.
- `services/hr_anchors.py` / `services/processing.py`: keep `athletes.resting_hr` at the measured 42-day mean unless the athlete pinned it (`resting_hr_source = 'manual'`).

### MCP Server

`mcp-server/` is a separate service, not a router on the FastAPI backend — see
[MCP_SERVER.md](./MCP_SERVER.md) for the full design. It exposes read-only Astraphe data
(workouts, biometrics, training load, coach memory) to external MCP clients like Claude,
authenticated via Supabase Auth's OAuth 2.1 Server mode rather than the interactive session
JWT the mobile app uses. It imports `backend/app/services/coach_tools.py`'s tool-handler
functions directly instead of duplicating them, so its data-access behavior is identical to
the in-app AI coach's. The main API rejects these third-party tokens (`client_id` claim).

### Photon Bridge

`photon-bridge/` is a small Node service that holds the Photon (iMessage) gRPC stream and talks to the backend over HTTP (`POST /v1/messaging/photon/inbound`, shared `PHOTON_BRIDGE_TOKEN`). It's single-user and off unless `PHOTON_ATHLETE_ID` and `PHOTON_ALLOWED_NUMBER` are set. See [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md).

### Data Layer

Supabase is the durable source of truth for auth, relational data, storage, and pgvector. The canonical schema history is in `supabase/migrations/`; see [DATA_MODELS.md](./DATA_MODELS.md).

Key tables include:

- `athletes`, `athlete_anchor_history`
- `workouts`, `activity_streams`, `activity_laps`
- `biometrics`, `sleep_periods`, `sleep_stage_segments`
- `heart_rate_series`, `hr_detection_dismissals`
- `weigh_ins`
- `tss_history`
- `training_plans`
- `oauth_tokens`
- `coach_conversations`, `coach_messages`, `coach_memories`
- `athlete_analyses`
- `push_tokens`, `notification_log`
- `messaging_events`

Most athlete-owned tables use RLS predicates that map `athlete_id` to `athletes.user_id = auth.uid()`.

### AI Layer

The coach uses the `google-genai` SDK. Defaults come from `backend/app/config.py`:

- `GEMINI_MODEL=gemini-3.5-flash-lite` (coach chat)
- `GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite` (when the chat model is overloaded or times out)
- `GEMINI_ANALYSIS_MODEL=gemini-3.1-flash-lite` (screen insights, memory extraction)
- `GEMINI_IMPORT_MODELS=gemini-3-flash-preview,gemini-3.8-flash,gemini-3.6-flash` (plan import, tried in order)
- `GEMINI_EMBEDDING_MODEL=gemini-embedding-2`

`LLM_PROVIDER=openai` (with `OPENAI_API_BASE_URL`) sends chat, insights, and memory extraction to any OpenAI-compatible endpoint instead; `CHAT_LLM_PROVIDER`/`CHAT_MODEL` move only the coach chat there, with Gemini as fallback. Embeddings always use Gemini. See `services/llm_provider.py`.

Admin overrides for coach/analysis models are stored in `auth.users.app_metadata`. User-editable metadata is not trusted for authorization or model selection.

Coach behavior is prompt-file driven from `backend/app/prompts/coach_behavior.md`. The agent loop supports custom tools (`services/coach_tools.py`), Google Search grounding or a SearXNG-backed `web_search` tool (`SEARXNG_URL`), document/image context, RAG memories, XML `<response>` extraction, and background memory persistence.

### Redis Layer

Redis is optional locally and expected in production, where the API runs as two replicas. It backs:

- Per-IP and per-athlete (AI and expensive-action) sliding-window rate limits (`core/rate_limiter.py`).
- Response caches: athlete state/profile/zones, activity streams and detail (`streams:`, `detail:` keyed by `zones_version:`), and the Body cache (`core/body_cache.py`: `GET /v1/biometrics` first page, `GET /v1/workouts` first page, heart-rate day, weight), retired together by bumping `body_version:{athlete_id}`.
- Cross-replica state: the shared Gemini free-tier quota (`services/gemini_quota.py`), per-athlete daily plan-import count (`services/plan_import.py`), the analysis regeneration lock (`routers/analysis.py`), coach reply progress (`services/coach_progress.py`), pending Garmin MFA logins (`services/garmin.py`), and single-use OAuth `state` nonces (`services/oauth_state.py`).

When `REDIS_URL` is not set or Redis is unreachable, rate limits and the shared state fall back to process-local memory and caches are simply missed. See [REDIS.md](./REDIS.md).

### Deployment Layer

Repo automation (`.github/workflows/deploy.yml`) on push to `main`:

1. Run backend, mobile, mcp-server, and photon-bridge tests; build and push the `ghcr.io/sbalbale/astraphe-api`, `astraphe-mcp`, and `astraphe-photon-bridge` images tagged with the commit SHA.
2. Sync `supabase/migrations` to a k3s node over Cloudflare Access SSH and run `supabase db push` against the cluster's Postgres (`supabase-db-0`, namespace `supabase`) before the API rolls out. Migrations must therefore stay backward-compatible with the previous release.
3. `kubectl set image` the `astraphe-api`, `astraphe-mcp`, and `photon-bridge` Deployments (namespace `astraphe`) and wait for rollout. (The `photon-bridge` job needs a one-time cluster bootstrap first; see [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md).)

The frontend is deployed to Firebase Hosting by the Firebase hosting workflows. See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Data Flows

### Authenticated API Request

```text
SvelteKit route
  -> Supabase session access token
  -> fetch() with Authorization header
  -> FastAPI dependency verifies the JWT locally against Supabase's JWKS
     (falls back to GoTrue auth.get_user()); rejects third-party OAuth tokens
  -> athletes.id lookup by user_id (cached in-process for 10 min)
  -> Supabase client for that token (LRU-cached; all share one httpx pool)
  -> RLS-scoped database query
```

### Workout Ingestion

```text
Manual/Strava/Garmin/WHOOP/Intervals.icu input, or HR auto-detection
  -> FastAPI sync or workout route, webhook, or poll loop
  -> source normalization, ownership verification, cross-source merge
     (a recorded workout replaces overlapping hr_detected ones)
  -> workout row
  -> TSS/HRSS/strain processing, day strain refresh
  -> tss_history update
  -> CTL/ATL/TSB recompute
  -> Redis cache invalidation; cached analysis refetched on next client request
```

### All-Day Heart Rate

```text
Garmin poll tick
  -> daily heart rate (2-minute grid) saved to heart_rate_series
  -> hr_activity_detection: flat runs dropped, windows above the HRR threshold
     saved as hr_detected workouts (unless overlapping a recorded workout or dismissed)
  -> day_strain recomputed with all-day minutes
  -> GET /v1/biometrics/heart-rate serves the day (Redis Body cache)
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
  -> POST /v1/coach/message/async (or /message, /stream)
  -> tier/model/rate limits from app_metadata; shared Gemini quota
  -> current context from athletes, biometrics, tss_history, workouts, training_plans
  -> relevant coach_memories via pgvector
  -> Gemini agent loop with tools and search grounding (progress steps to Redis)
  -> XML response extraction
  -> response saved to coach_messages; push sent if the chat isn't open
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
     (one replica regenerates at a time, Redis lock)
  -> content/fingerprint/model/cached response
```

## Security Model

- Supabase Auth access tokens are required for protected routes; signatures are verified locally (ES256/RS256 via JWKS) or by GoTrue.
- Tokens from Supabase's OAuth server for third-party (MCP) clients are rejected by the API and blocked from writes by restrictive RLS policies.
- `app_metadata` is the source of truth for tier, trial end, admin status, AI model overrides, and rate-limit overrides.
- `user_metadata` is never used for authorization.
- RLS remains enabled on all public tables.
- Production disables FastAPI interactive docs.
- `APP_ENV` defaults to `production` (fail closed).
- Production startup rejects `TEST_ATHLETE_ID` and a missing/invalid `OAUTH_TOKEN_ENCRYPTION_KEY`.
- Security headers are added to all responses.
- CORS origins are enumerated in `backend/app/main.py`; the LAN-IP regex is dev-only.
- Push, OAuth, and service-role credentials stay server-side; provider tokens are encrypted at rest.
- Debug routes are not registered in production.

## Scaling Notes

The API holds no per-request state; shared state lives in Supabase and Redis, so multiple replicas run concurrently (two in production). Work that must happen once (token refresh, Garmin sync, notifications, analysis regeneration) is claimed through a DB row or Redis lock. Recalculation and backfill work still runs inside API background tasks; if traffic grows materially, those jobs should move to a dedicated worker queue.
