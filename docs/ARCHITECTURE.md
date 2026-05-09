# System Architecture

## Overview

ASTRAPE is composed of five decoupled layers: a native mobile client, a Python computation + API backend, an AI intelligence layer, a cached AI analysis layer, and a persistent data layer. Each communicates via well-defined async interfaces.

```
┌──────────────────────────────────────────────────────────────┐
│                        MOBILE CLIENT                         │
│          Svelte 5 + SvelteKit 2 + Capacitor 6 (iOS/Android)  │
│          LayerChart / D3 · HealthKit · Supabase Auth JWT      │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTPS / SSE
┌───────────────────────────▼──────────────────────────────────┐
│                      FASTAPI GATEWAY                         │
│     Python 3.12 · Async · Google Cloud Run · Docker          │
│                                                              │
│  Routers: athlete · workouts · biometrics · coach · sync     │
│           plan · training-plans · analysis · debug           │
└────────────┬──────────────────────────┬──────────────────────┘
             │ NumPy / Pydantic          │ google-genai SDK
┌────────────▼────────────┐  ┌──────────▼──────────────────────┐
│    COMPUTE ENGINE       │  │         AI LAYER                 │
│  CTL/ATL/TSB/TSS/RDY   │  │   Gemma 4 26B (coach)        │
│  Recovery Score         │  │   Gemini Flash Lite latest (analysis)   │
│  NumPy vectorized ops   │  │   Function Calling · RAG         │
└────────────┬────────────┘  └──────────┬──────────────────────┘
             │ SQL                       │ pgvector
┌────────────▼───────────────────────────▼──────────────────────┐
│                        DATA LAYER                             │
│              Supabase PostgreSQL + pgvector                   │
│  athletes · workouts · biometrics · tss_history               │
│  training_plans · coach_conversations · coach_messages        │
│  coach_memories · oauth_tokens · ai_analysis_cache            │
└───────────────────────────────────────────────────────────────┘
                            │ GCS
                    ┌───────▼───────┐
                    │  Cloud Storage │
                    │ Raw FIT blobs  │
                    └───────────────┘
```

---

## Service Responsibilities

### Mobile Client (Svelte 5 + Capacitor 6)

A SvelteKit single-page application compiled into a native iOS/Android shell via Capacitor. It is a pure presentation and interaction layer — no business logic or metric computation runs here.

**Key responsibilities:**
- Render real-time telemetry visualizations via LayerChart / D3 SVG
- Collect HealthKit data on-device via Capacitor Background Runner and POST batches to the API
- Authenticate users via Supabase Auth JWT and attach tokens to all API requests
- Stream AI coach responses via Server-Sent Events
- Enforce tier-based UI gating (premium badge, feature locks)

**What it explicitly does NOT do:**
- Calculate TSS, CTL, ATL, or TSB
- Store raw workout or biometric data locally beyond a session-level memo cache
- Hold API keys or OAuth secrets of any kind

---

### Computation API (FastAPI on Cloud Run)

The FastAPI service is the system's mathematical and orchestration core. It is stateless and horizontally scalable. All instances share state only through Supabase.

**Key responsibilities:**
- Receive raw workout payloads and compute TSS using sport-specific normalized power / IF calculations
- Maintain rolling CTL/ATL windows via NumPy vectorized operations over `tss_history`
- Manage OAuth 2.0 token lifecycles for Garmin and WHOOP
- Construct AI context payloads and call the Google AI API
- Serve RAG-augmented coaching responses via SSE using pgvector similarity search
- Produce and cache screen-level AI analysis insights (recovery, sleep, strain, training load, dashboard, workout)
- Enforce tier-based access (`free` | `trial` | `premium`) on coach, plan, and AI analysis endpoints

---

### AI Layer

Two models serve distinct roles:

| Model | Role | Trigger |
|---|---|---|
| Gemma 4 26B | Full AI coach — conversational, context-aware, multi-turn, function calling | `POST /coach/message` |
| Gemini Flash Lite latest (or configured override) | Short-form screen analysis — recovery, sleep, strain, training load, workout insight | `GET /analysis/*` |

The coach uses **function calling** so it can autonomously fetch athlete state, schedule training plan sessions, or clear the calendar mid-conversation. The analysis layer uses a **deterministic fallback** for free-tier athletes — rule-based summaries are generated without a Gemini call.

---

### Data Layer (Supabase PostgreSQL + pgvector)

Supabase provides three things ASTRAPE needs from a single managed service: a relational PostgreSQL database, Row Level Security for multi-tenant data isolation, and the pgvector extension for embedding-based similarity search.

**Key tables:**
- `athletes` — user profiles, physiological anchors, subscription tier
- `workouts` — normalized workout records from all sources
- `biometrics` — daily HRV, RHR, sleep, strain, and body temperature readings
- `tss_history` — computed daily TSS values (source of truth for CTL/ATL)
- `training_plans` — structured session blocks with AI-generated structure and context
- `coach_conversations` / `coach_messages` — persisted conversation threads
- `coach_memories` — embedded conversation chunks for RAG retrieval
- `ai_analysis_cache` — cached insight strings keyed by type + scope + data fingerprint
- `oauth_tokens` — encrypted third-party provider credentials

---

## Data Flows

### Workout Ingestion

```
1. User completes workout (Garmin / WHOOP / Apple Watch)
      │
2. Webhook: POST /sync/garmin/webhook  or  POST /sync/whoop/webhook
   (or HealthKit: POST /workouts via Capacitor Background Runner)
      │
3. API validates webhook HMAC signature
      │
4. Raw payload normalized to internal WorkoutPayload
      │
5. TSS computed (NP-based for cycling, pace-HR for running)
      │
6. Workout row inserted into `workouts`
      │
7. `tss_history` upserted with daily_tss aggregate
      │
8. CTL / ATL rolling averages recomputed for athlete (NumPy)
      │
9. `tss_history` updated with ctl, atl, tsb
      │
10. Supabase Realtime pushes update → mobile client re-renders
```

---

### AI Coach Query

```
1. User sends message in Coach screen
      │
2. POST /coach/message  {conversation_id, message}
      │
3. API checks tier: 403 if not premium
      │
4. API fetches current athlete context:
   - CTL, ATL, TSB (from tss_history)
   - Last 14d HRV trend (from biometrics)
   - Recent workouts (last 7)
   - Upcoming training plan (next 7 days)
      │
5. pgvector similarity search over coach_memories
   (retrieves relevant prior coaching context, k=5)
      │
6. System prompt + context + memories + history assembled
      │
7. Gemma 4 26B called with function_calling tools:
   get_athlete_state · get_recent_workouts · get_training_plan
   schedule_training_plan · clear_training_plans
      │
8. Tool hops executed (up to max_tool_hops) until model returns text
      │
9. Response streamed back to client via SSE
      │
10. Full response stored in coach_messages
11. Embedding generated and stored in coach_memories (background)
```

---

### AI Analysis (Screen Insights)

```
1. Mobile screen mounts (Dashboard, Recovery, Strain, Training)
      │
2. GET /analysis/{type}?day=YYYY-MM-DD
      │
3. API builds context dict for the requested type:
   - biometrics context (recovery/sleep/strain)
   - tss_history context (training-load)
   - blended context (dashboard-summary)
   - workout row (workout/{id})
      │
4. Fingerprint computed (SHA-256 of context dict)
      │
5. Cache lookup: if fingerprint matches ai_analysis_cache → return cached
      │
6. Cache miss:
   - free/trial tier → deterministic rule-based summary (no LLM call)
   - premium tier   → Gemini Flash Lite call
      │
7. Result written to ai_analysis_cache
      │
8. { content, fingerprint, cached, model } returned to client
```

---

## Scalability Model

Cloud Run scales to zero when idle (zero cost) and scales horizontally under load. Each instance is stateless, so no session affinity is required. The Supabase connection pool (via PgBouncer) handles concurrent database connections without exhausting the PostgreSQL instance.

For launch targeting individual athletes: 0–10 Cloud Run instances is sufficient. At scale (10k+ DAUs), the TSS recalculation jobs should be extracted into Cloud Tasks or a dedicated worker pool.

---

## Security Model

- All API endpoints require a valid Supabase JWT (`Authorization: Bearer <token>`)
- `tier` is read from `athletes.tier` (admin-controlled column), not from user-editable auth metadata
- Supabase Row Level Security ensures athletes can only query their own records at the database layer — a second line of defense after the API validates the JWT
- Garmin and WHOOP OAuth tokens are stored encrypted at rest via Supabase Vault
- Webhook endpoints validate HMAC signatures before processing any payload
- The mobile client never receives or stores third-party OAuth tokens
- The debug router is disabled (`404`) in all non-development environments
