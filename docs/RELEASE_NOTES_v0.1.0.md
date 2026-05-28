# ASTRAPHE AI Coach — Release Notes (v0.1.0 / MVP)

**Tag:** [`v0.1.0`](https://github.com/sbalbale/astraphe-ai-coach/releases/tag/v0.1.0)  
**Purpose:** Detailed description of what is implemented today (MVP-ready slice), how the pieces fit together, and how this release differs from future roadmap items.

---

## 1. Executive summary

This release is an end-to-end **precision coaching platform** comprising:

1. **A FastAPI backend** (Python 3.12) that owns all training-load math (TSS, CTL, ATL, TSB, composite recovery/readiness), ingests wearable data via **WHOOP** (OAuth + webhooks + backfill), receives **Garmin Connect** webhook payloads when configured, accepts **Apple HealthKit** batches from the mobile client, persists state in **Supabase PostgreSQL**, and exposes **premium-gated conversational AI coaching** plus **tier-aware screen analysis** backed by Google’s **Gemini / Gen AI** APIs and **pgvector** RAG memories.
2. **A Supabase-first data layer** with Row Level Security, coach chat persistence, embeddings, AI analysis caching, OAuth token storage, and a growing migration history (see §5).
3. **A SvelteKit 5 + Capacitor 8 mobile app** (`mobile/`) for iOS/Android: dashboards, training views, conversational coach UX (SSE), HealthKit ingestion, OAuth handoff UX for WHOOP, and Supabase-realtime-assisted client patterns.

Non-goals in *code* at this tag: **Strava** ingestion is specified in [`STRAVA_INTEGRATION.md`](./STRAVA_INTEGRATION.md) but **there is no `strava` service or routes in the backend repository at v0.1.0**. Treat Strava as a documented product/engineering roadmap, not a shipped integration.

---

## 2. Versioning & repository facts

| Item | Value |
|------|------|
| **Semantic version** | `0.1.0` (first tagged MVP slice) |
| **Backend OpenAPI title** | ASTRAPHE Backend API (`main.py`; internal `version` field is `"1.0.0"` — marketing vs. semver are separate) |
| **Mobile npm version** | `0.0.1` (`mobile/package.json`; app store versioning is orthogonal) |
| **Primary docs** | `README.md`, `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/DATA_MODELS.md`, `docs/DEPLOYMENT.md`, `docs/AI_COACH.md`, `docs/ALGORITHMS.md` |

Canonical GitHub repo name (per remote hint): **`sbalbale/astraphe-ai-coach`**.

---

## 3. Runtime stack (as pinned or declared in repo)

### Backend (`backend/`)

- **Language:** Python 3.12 (Docker base `python:3.12-slim`)
- **Web:** FastAPI + Uvicorn
- **Config:** `pydantic-settings` (`app/config.py`) — `.env`-driven Supabase URLs/keys and Gemini-related model overrides
- **Database client:** `supabase-py` with two access patterns:
  - **User-scoped client** (`get_user_db`): JWT attached to PostgREST so **RLS applies**
  - **Service-role client** (`get_admin_db`): webhooks and privileged writes
- **Math / data:** NumPy, Pandas
- **AI:** `google-genai` SDK — orchestration in `app/services/ai_coach.py`, embeddings for RAG, analysis generation in `app/services/analysis_cache.py`

### Mobile (`mobile/`)

- **Svelte** 5.x, **SvelteKit** 2.x, **Vite** 8.x
- **Capacitor** 8.x (iOS/Android), **Background Runner** plugin for HealthKit batching
- **Health:** `@interval-health/capacitor-health`
- **Charts:** LayerChart, D3
- **Auth / realtime:** `@supabase/supabase-js`
- **Content safety / rich text:** DOMPurify, Marked, KaTeX extensions

### Data & platform

- **Supabase:** PostgreSQL, Auth, RLS, Realtime; **pgvector** for `match_coach_memories` RPC used by the coach
- **Deployment target (documented):** Google Cloud Run + Secret Manager + optional GCS for raw FIT blobs (see `docs/DEPLOYMENT.md`)

---

## 4. Backend — surface area (routers & behavior)

All authenticated JSON routes are mounted under the configurable prefix **`/v1`** (`settings.API_PREFIX`), except where noted. The app registers:

| Router module | Role |
|---------------|------|
| `athlete` | Profile and **aggregated athlete state** (CTL/ATL/TSB, biometrics rollups, onboarding helpers) |
| `workouts` | Completed workout ingest (e.g. HealthKit), listing, deletion with **TSS ledger / PMC recomputation** |
| `biometrics` | Daily biometrics ingest + rich **history with z-scores** and pagination |
| `coach` | **SSE-streamed** conversational coach, conversation CRUD, image-aware chat payloads; **premium-only** for coach actions |
| `sync` | **WHOOP OAuth** (authorize/callback), **WHOOP webhooks**, **Garmin webhooks**, integration status, unlink |
| `plan` | Legacy/mobile-friendly **plan projection** (premium-gated) |
| `training_plans` | Full **CRUD** for structured planned sessions including JSON `structure` (intervals) |
| `analysis` | Cached **Gemini** (or rule-based) insights: recovery, sleep, strain, training load, dashboard summary, per-workout, time-in-zones |
| `debug` | Development-only connectivity checks (**404 outside `APP_ENV=development`**) |

**Health (no auth):** `GET /health` — liveness.

### 4.1 Authentication & identity

- **Bearer token** = Supabase session JWT on protected routes.
- **`get_current_athlete`** resolves `auth.users` → `athletes.id` via `db.auth.get_user` + `athletes` lookup.
- **Development escape hatch:** If `APP_ENV=development` and `TEST_ATHLETE_ID` is set, failed auth can fall back to that athlete id when the row exists (intended for local iteration only).

### 4.2 Subscription / tier gating (implementation truth)

**Important:** Project documentation in places describes `athletes.tier` as authoritative. **At v0.1.0, `get_current_user_tier()` reads `tier` from Supabase Auth `app_metadata` / `user_metadata`**, normalizes to `free | trial | premium`, and defaults to `free` on errors.

| Feature area | Tier behavior in code |
|--------------|------------------------|
| **`/coach/*`** | **`premium` only** (`403` otherwise) |
| **`/plan`** | **`premium` only** |
| **`/analysis/*`** (most types) | **`trial` and `premium`** may receive Gemini-backed analysis; **`free`** uses deterministic / rule-based fallbacks (see `analysis.py` helpers) |
| **Workouts / biometrics / athlete state** | Generally available to authenticated athletes regardless of tier (subject to RLS) |

Operators should set tiers via **Supabase Auth metadata** (or align metadata with `athletes.tier` if you maintain both).

### 4.3 Workout & load pipeline

**Entry points:**

- **POST `/v1/workouts`** — Mobile HealthKit batches and manual API clients.
- **WHOOP webhook** — `recovery.updated`, `sleep.updated`, `workout.updated` mapped into `DailyBiometrics` / `WorkoutPayload` and passed to **`process_and_save_*`** background tasks with token refresh on `401`.
- **Garmin webhook** — Parses `activities` arrays and queues `process_and_save_workout`; optional body-composition updates to `weight_kg`.

**Processing highlights (`app/services/processing.py`):**

- **TSS:** Sport-aware paths — e.g. **cycling** normalized power vs FTP, **running** pace vs threshold pace, **HRSS-from-zones** when power/pace inadequate, **rowing watt normalization** (`normalize_rowing_watts`).
- **`tss_history` ledger:** `recalculate_tss_history` aggregates **daily TSS using the athlete’s `timezone_offset_min`** so CTL/ATL/TSB align with the athlete’s local calendar day boundary.
- **PMC extension through “today”:** Inserts explicit **zero-TSS future days** so EWMA curves **decay on rest days** instead of collapsing to artificial zeros at the tail.
- **Downstream scores:** Sleep score modeling, strain, composite recovery, readiness (see §6).

### 4.4 Integrations status

#### WHOOP (implemented)

- **OAuth 2.0** authorize + callback with deep-link **`astraphe://connected?...`** and polished HTML splash for desktop browsers.
- **Token persistence** in `oauth_tokens` (plaintext fields in MVP schema — tighten for production vault encryption per your threat model).
- **90-day historical backfill** kicked off post-callback (`whoop_backfill`).
- **Webhooks:** Fetch enriched records by id; handles token rotation; tolerant of flaky disconnects (**returns `200`** to discourage harmful retries where appropriate).

#### Garmin (partially implemented)

- Webhook route accepts Garmin push shapes and maps activities using stored Garmin user linkage (`get_athlete_by_garmin_id`).
- **Webhook HMAC verification is not strictly enforced** in code paths inspected at this release (signature may be absent / skipped) — treat as **MVP lax** and harden before public production.

#### Strava (**not implemented in backend code at v0.1.0**)

- Comprehensive design: OAuth, push subscription, streams to object storage, deduplication policies — **`docs/STRAVA_INTEGRATION.md`**.
- **No routes, secrets, or `services/strava.py` in tree** matching the integration.

---

## 5. Database & migrations (Supabase)

Initial schema (`20260427000000_initial_schema.sql`) establishes core tables (`athletes`, `workouts`, `biometrics`, `tss_history`, etc.). Subsequent migrations add, among others:

- **Athlete profile richness:** HR zones metadata, thresholds, gender, pace units, timezone offset, mobility/rowing sport enums, unified score naming.
- **AI & coach persistence:** Coach conversations/messages, `match_coach_memories` embedding search, athlete-level AI caches (`ai_analysis_cache` evolution), dashboard summary analysis type, workout zone / time-in-zones analysis scopes.
- **Training plans:** `structure` JSONB for nested intervals.
- **Sleep modeling:** sleep periods, in-bed minutes, nap flags, related biometrics columns.
- **Operational / per-user overrides:** migrations that pin **Gemini model names per account** via Supabase-managed metadata routes (multiple timestamped commits in history — reconcile in your deployed project to a single policy).

**RLS:** Enforced per table against `auth.uid()` as documented in [`DATA_MODELS.md`](./DATA_MODELS.md).

---

## 6. Algorithms & physiology engine (`app/services/algorithms.py`)

Pure numerical layer (no I/O). Notable behaviors shipped or tested:

- **Cycling TSS** (`calculate_cycling_tss` etc.) aligned with NP/FTP IF semantics.
- **CTL / ATL:** EWMA-style rolling accumulators with **cold-start mitigation** consistent with PMC best practices documented in-repo.
- **TSB:** Derived from CTL/ATL positioning (Banister-inspired training impulse variants documented in `ALGORITHMS.md`).
- **Strain:** Zone-minute-weighted cardiovascular load scaled to interpreted strain bands.
- **Recovery / readiness:** Multi-factor composites with explicit weighting philosophy in README/architecture docs.
- **HR zones → stress:** Tiered midpoint model with gender/source-aware threshold HR estimation hooks (`compute_hrss_from_zones` tests in `tests/test_algorithms.py`).

---

## 7. AI coach (`app/services/ai_coach.py` + prompts)

### 7.1 Conversational coach

- **Model selection:** Primarily **`settings.GEMINI_MODEL`** (see `dependencies.get_current_gemini_model` — currently resolves to configured Flash-class model name with safeguards against stale metadata IDs).
- **Context assembly:** Rolling biometrics summaries, PMC position, workout windows, retrieved **pgvector memories** (`retrieve_relevant_memories` embedding via configured embedding model).
- **Tool execution:** Implemented in `coach_tools.py` — includes scheduling/updating **`training_plans`**, querying athlete state/workouts, and **scenario simulation** helpers (e.g. projecting CTL/ATL after hypothetical TSS).
- **Streaming:** SSE from `coach` router using async bridges; persists assistant turns and triggers memory embedding writes post-response.
- **Coach instructions:** Loaded from `app/prompts/coach_behavior.md` when present.

### 7.2 Screen-level analysis (`/v1/analysis/*`)

- **Fingerprinted cache** in `ai_analysis_cache` — avoids repeat LLM spend when underlying inputs are unchanged.
- **Model:** `get_current_gemini_analysis_model` prefers Auth `app_metadata.gemini_analysis_model`, falls back to `GEMINI_ANALYSIS_MODEL` env default.
- **Tier fallbacks:** Free users receive **deterministic narrative** where policy dictates; premium/trial paths call Gemini and store results.

---

## 8. Mobile client (feature-level)

The mobile app is a **SvelteKit SPA** adapted for static hosting inside Capacitor.

**Implemented UX surfaces (from repository layout / docs):**

- Dashboard, training, plan, zones, recovery, sleep, strain, coach chat, connect flows, profile.
- **API client** with typed shapes and **SSE** handling for coach streaming.
- **Offline-first memo cache** patterns (`lib/cache.ts`).
- **HealthKit** ingestion path posting to backend workout/biometrics endpoints.
- **Charts:** LayerChart / D3 visualizations for trends.

**Explicit non-responsibilities:** No server-side metrics — the device never becomes the source of truth for CTL/ATL/TSB.

---

## 9. Testing & quality

**Backend tests** (`backend/tests/`):

- `test_algorithms.py` — TSS, rowing normalization, HRSS-from-zones sanity.
- `test_hr_zones.py` — zone engine edge cases.
- `test_coach.py`, `test_coach_tools.py` — coach/tool orchestration behaviors.
- `test_webhooks.py` — integration-style webhook coverage.
- `test_training_plans_model.py` — plan schema / mapping.
- `conftest.py` — fakes for Supabase interactions (including deterministic insert ids where needed).

**Mobile:** `vitest` script present; run `npm test` in `mobile/` for unit coverage of client utilities.

**Notable gap:** No automated load/chaos suite — scale guidance remains architectural (Cloud Run + pool limits).

---

## 10. Security & operational notes (honest MVP caveats)

1. **Webhook authenticity:** WHOOP signature verification code paths exist but may be **commented or bypassed** in places for dev velocity — re-enable before exposure to the open internet.
2. **OAuth token storage:** Review encryption-at-rest requirements vs current `oauth_tokens` columns for your compliance target.
3. **CORS:** `allow_origins=["*"]` in `main.py` — acceptable for early mobile API usage but tighten when you publish a browser-hosted admin portal.
4. **Debug endpoints:** Automatically **404** when `APP_ENV` is not `development`.
5. **Rate limiting:** Not implemented at FastAPI layer (relies on platform throttles).

---

## 11. Deployment artifacts

- **`backend/Dockerfile`** — Slim Python image, exposes `8000`.
- **`backend/cloudbuild.yaml`** — GCP Cloud Build CI path (see `docs/DEPLOYMENT.md` for secrets & service accounts).
- **Root Supabase tooling** via `package.json` scripts invoking Supabase CLI for migrations (`supabase db push`, etc.).

---

## 12. Documentation map

Use these alongside this release note:

| Document | Contents |
|---------|----------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Topology, scaling, conceptual data flows |
| [`API_REFERENCE.md`](./API_REFERENCE.md) | Request/response examples for each route family |
| [`DATA_MODELS.md`](./DATA_MODELS.md) | Table-level schema & RLS |
| [`ALGORITHMS.md`](./ALGORITHMS.md) | Derivation narratives for PMC + scores |
| [`AI_COACH.md`](./AI_COACH.md) | Prompting / RAG / tool strategy |
| [`DEPLOYMENT.md`](./DEPLOYMENT.md) | Cloud Run rollout & secrets |
| [`STRAVA_INTEGRATION.md`](./STRAVA_INTEGRATION.md) | **Roadmap-only** backend design for Strava |
| [`MOBILE.md`](./MOBILE.md) | Capacitor / HealthKit operational detail |

---

## 13. What we’d call “next milestone” candidates

Concrete engineering follow-ups implicit by repo state:

1. **Implement Strava** per `STRAVA_INTEGRATION.md** (OAuth, subscription lifecycle, DetailedActivity archival, streams to object storage, dedupe).
2. **Harden webhooks:** mandatory HMAC, structured logging (replace `print` in hot paths), idempotency keys for WHOOP deliveries.
3. **Unify tier source of truth** — choose `athletes.tier` *or* Auth metadata and enforce consistently in API + dashboards.
4. **Garmin ingestion parity** — complete activity detail fetch pipeline if webhook only carries summaries.
5. **Production readiness:** Secret Manager wiring for all integrations, tighten CORS, structured observability (OpenTelemetry).

---

## 14. Changelog anchor (repository state at tag)

Representative finalized work visible at **`v0.1.0`**:

- Timezone-aware **UTC handling** across services with legacy **`Z`** wire suffix compatibility.
- PMC / biometrics ingest respects athlete **`timezone_offset_min`** when bucketing calendar days.
- Documentation updates for wearable integration strategies (including Strava documentation — design, not shipped code).

For an exact file-level history: `git log v0.1.0` (or compare to prior tags once they exist).

---

*End of v0.1.0 MVP release notes.*
