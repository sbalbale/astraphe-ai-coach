# Architecture

## Overview

ASTRAPE is structured as a four-layer system: a native mobile client, a stateless computation API, a third-party telemetry ingestion layer, and a persistent data + vector store. Each layer has a single, clearly bounded responsibility.

```
┌─────────────────────────────────────────────────────────────────┐
│                     MOBILE CLIENT LAYER                         │
│                                                                 │
│   Svelte 5 + Capacitor (iOS / Android)                         │
│   ├── LayerChart (D3-backed SVG telemetry visualization)        │
│   ├── Capacitor Background Runner (HealthKit sync)              │
│   └── Capacitor HTTP (API communication)                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS / REST
┌────────────────────────────▼────────────────────────────────────┐
│                    COMPUTATION API LAYER                        │
│                                                                 │
│   FastAPI (Python 3.12) → Docker → Google Cloud Run            │
│   ├── /athlete     — athlete state & metric computation         │
│   ├── /workouts    — workout ingestion & TSS calculation        │
│   ├── /coach       — Gemini AI agent endpoint                   │
│   ├── /sync        — webhook receivers & OAuth token refresh    │
│   └── /plan        — training plan generation & scheduling      │
└──────┬─────────────────────┬──────────────────────┬────────────┘
       │                     │                      │
┌──────▼──────┐   ┌──────────▼─────────┐  ┌────────▼───────────┐
│  TELEMETRY  │   │    AI LAYER        │  │   DATA LAYER       │
│  LAYER      │   │                    │  │                    │
│             │   │  Google Gemini     │  │  Supabase          │
│  Garmin     │   │  2.5 Pro           │  │  PostgreSQL        │
│  Connect    │   │  ├── Function      │  │  ├── pgvector      │
│  API        │   │  │   Calling       │  │  ├── Row-level     │
│             │   │  ├── Structured    │  │  │   Security      │
│  WHOOP      │   │  │   Output        │  │  └── Realtime      │
│  API        │   │  └── RAG Context   │  │      Subscriptions │
│             │   │      (pgvector)    │  │                    │
│  Apple      │   └────────────────────┘  └────────────────────┘
│  HealthKit  │
│  (on-device)│
└─────────────┘
```

---

## Service Responsibilities

### Mobile Client (Svelte 5 + Capacitor)

The client is a Svelte 5 single-page application compiled and wrapped by Capacitor into a native iOS/Android binary. It does not perform any business logic or metric computation — it is purely a presentation and interaction layer.

**Key responsibilities:**
- Render real-time telemetry visualizations via LayerChart / D3 SVG
- Collect HealthKit data natively via Capacitor Background Runner and POST it to the API
- Manage UI state (selected screen, active tweaks, date range filters)
- Authenticate users via Supabase Auth JWT and attach tokens to all API calls
- Stream AI coach responses via server-sent events (SSE)

**What it explicitly does NOT do:**
- Calculate TSS, CTL, ATL, or TSB (always server-computed)
- Store raw workout or biometric data locally beyond a session cache
- Hold API keys or OAuth secrets of any kind

### Computation API (FastAPI on Cloud Run)

The FastAPI service is the system's mathematical and orchestration core. It is stateless and horizontally scalable. All instances share state only through the Supabase database.

**Key responsibilities:**
- Receive raw workout payloads and compute TSS using sport-specific normalized power / IF calculations
- Maintain rolling CTL/ATL windows via NumPy vectorized operations over stored TSS history
- Manage OAuth 2.0 token lifecycles for Garmin and WHOOP
- Construct AI context payloads and call the Gemini API
- Serve RAG-augmented coaching responses using pgvector similarity search

### Data Layer (Supabase PostgreSQL + pgvector)

Supabase provides the relational backbone and the vector search capability required for the AI coach's long-term memory.

**Key tables:**
- `athletes` — user profiles, physiological anchors (max HR, FTP, weight)
- `workouts` — normalized workout records from all sources
- `biometrics` — daily HRV, RHR, sleep, and body temperature readings
- `tss_history` — computed daily TSS values (source of truth for CTL/ATL)
- `training_plans` — structured weekly plan blocks
- `coach_memories` — embedded conversation chunks for RAG retrieval

---

## Data Flow: Workout Ingestion

```
1. User completes workout (Garmin / WHOOP / Apple Watch)
      │
2. Webhook fires → POST /sync/garmin or /sync/whoop
      │
3. API validates webhook signature
      │
4. Raw payload normalized to internal WorkoutSchema
      │
5. TSS computed (NP-based for cycling, pace-HR for running)
      │
6. Workout + TSS persisted to Supabase
      │
7. CTL / ATL rolling averages recomputed for athlete
      │
8. Athlete state record updated (CTL, ATL, TSB)
      │
9. Supabase Realtime pushes update → mobile client re-renders
```

## Data Flow: AI Coach Query

```
1. User sends message in Coach screen
      │
2. POST /coach/message  {athlete_id, message, conversation_id}
      │
3. API fetches current athlete state:
   - CTL, ATL, TSB (from tss_history)
   - Last 7d HRV trend (from biometrics)
   - Recent workouts (last 5)
   - Sleep summary (last 3 nights)
      │
4. pgvector similarity search over coach_memories
   (retrieves relevant prior coaching context)
      │
5. Structured context object assembled
      │
6. Gemini 2.5 Pro called with:
   - System prompt (ASTRAPE persona + constraints)
   - Athlete context (structured JSON)
   - RAG memories
   - Conversation history (last 10 turns)
   - User message
      │
7. Response streamed back via SSE
      │
8. Response + embedding stored in coach_memories
```

---

## Scalability Model

Cloud Run scales to zero when idle (no cost) and scales horizontally under load. Each instance is stateless, so no session affinity is required. The Supabase connection pool (via PgBouncer) handles concurrent database connections without overwhelming the PostgreSQL instance.

For the initial launch targeting individual athletes, a single Cloud Run service with a minimum of 0 instances and a maximum of 10 is sufficient. At scale (10k+ daily active athletes), the computation-heavy TSS recalculation jobs should be extracted into Cloud Tasks or a dedicated Celery worker pool.

---

## Security Model

- All API endpoints require a valid Supabase JWT (`Authorization: Bearer <token>`)
- Supabase Row Level Security (RLS) ensures athletes can only query their own records at the database layer — a second line of defense after the API validates the JWT
- Garmin and WHOOP OAuth tokens are stored encrypted at rest using Supabase Vault
- Webhook endpoints validate HMAC signatures before processing any payload
- The mobile client never receives or stores third-party OAuth tokens


