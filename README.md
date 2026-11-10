# ASTRAPHE — AI Coaching Platform

> **Endurance coaching built on your own physiological data and an AI coach.**

ASTRAPHE is a multi-source, AI-driven endurance coaching platform. It pulls workouts and recovery data from Garmin Connect, Strava, WHOOP, and intervals.icu, computes training load, recovery, and strain server-side, and puts a conversational AI coach on top of that data.

![Svelte](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-AI-886FBF?logo=googlegemini&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white)
![License](https://img.shields.io/badge/License-Apache_2.0-blue)

---

## What ASTRAPHE Does

**1. Aggregates data from several sources.**
Workouts, heart rate, HRV, sleep, and other biometrics come in from Garmin Connect (via the community `garminconnect` library), Strava, WHOOP, and intervals.icu. Overlapping records from different sources are merged into one canonical workout. Apple HealthKit is scaffolded in the app but does not ingest data yet.

**2. Computes the metrics that matter.**
TSS, CTL, ATL, and TSB are computed server-side with NumPy. Recovery, readiness, sleep, and strain scores come from transparent formulas in `backend/app/services/algorithms.py`, not device black boxes.

**3. Tracks the whole day, not just workouts.**
- **All-day heart rate** — Garmin's daily heart rate series is stored per day and shown on a zoomable Heart rate screen.
- **Workout auto-detection** — sustained elevated heart rate in the all-day series is saved as a detected workout (source `hr_detected`); any recorded workout from a device takes priority.
- **Day strain** — strain counts heart-rate minutes outside workouts as well as the workouts themselves.
- **Weight tracking** — multiple weigh-ins per day, a goal weight, and a Weight screen.

**4. Plans and coaches.**
- Training plans with automatic matching of recorded workouts to planned sessions; the coach can import a plan from a file or text.
- An AI coach (Gemini by default, or any OpenAI-compatible endpoint) that gets the athlete's current numbers on every turn, uses tools to query their data, and keeps long-term memories with vector search.
- Push notifications (FCM and web push) for readiness, digests, and weekly summaries.
- Optional extras: an MCP server so Claude and other MCP clients can read your data, and an iMessage coach channel via Photon.

---

## Architecture

```
┌───────────────────────────────────────────┐
│  Web / iOS app (SvelteKit + Capacitor)    │
│  Static build on Firebase Hosting         │
└───────────────────┬───────────────────────┘
                    │ HTTPS / SSE
┌───────────────────▼───────────────────────┐
│  astraphe-api (FastAPI, Docker image)     │
│  Production: k3s, 2 replicas + Redis      │
└──────┬──────────────┬──────────────┬──────┘
       │              │              │
┌──────▼─────┐ ┌──────▼────────┐ ┌───▼──────────────┐
│ Gemini /   │ │ Garmin, Strava│ │ Supabase         │
│ OpenAI-    │ │ WHOOP,        │ │ Postgres + RLS   │
│ compatible │ │ intervals.icu │ │ pgvector, Auth,  │
│ LLM        │ │               │ │ Storage          │
└────────────┘ └───────────────┘ └──────────────────┘
```

Also in the repo: `mcp-server/` (MCP server, its own image and deployment) and `photon-bridge/` (Node bridge for the iMessage channel).

---

## Repository Structure

```
astraphe-ai-coach/
├── README.md
├── .env.example               ← Pointer to the backend/mobile .env.example files
├── docker-compose.yml         ← Local Redis for dev
├── package.json               ← Supabase CLI + migration scripts
├── pytest.ini                 ← Backend test config (run pytest from the repo root)
│
├── docs/                      ← Documentation (see index below)
│
├── backend/                   ← FastAPI service (Python 3.12)
│   ├── Dockerfile
│   ├── dev.ps1                ← Windows dev launcher (uvicorn with timestamped logs)
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py          ← pydantic-settings, reads backend/.env
│   │   ├── dependencies.py    ← auth, rate limiting
│   │   ├── core/
│   │   ├── models/            ← Pydantic schemas
│   │   ├── prompts/           ← AI coach system prompts
│   │   ├── routers/           ← API endpoints
│   │   └── services/          ← algorithms, provider sync, AI coach
│   ├── scripts/               ← one-off ops/maintenance scripts
│   └── tests/                 ← pytest suite
│
├── mobile/                    ← Svelte 5 + SvelteKit + Capacitor (iOS)
│   ├── capacitor.config.ts
│   ├── firebase.json          ← Firebase Hosting config
│   ├── src/
│   │   ├── routes/            ← SvelteKit pages
│   │   └── lib/               ← api client, stores, components, utils
│   └── ios/                   ← native iOS project (no Android project yet)
│
├── mcp-server/                ← MCP server (Python)
├── photon-bridge/             ← iMessage bridge (Node)
│
└── supabase/                  ← Postgres schema (source of truth)
    ├── config.toml
    ├── migrations/            ← SQL migrations, RLS policies
    ├── templates/             ← Auth email templates
    ├── seed_athlete.sql       ← Dev test user + athlete
    └── seed_garmin_demo.sql   ← Dev demo training data
```

---

## Core Metrics

| Metric | Abbr | Formula | Description |
|---|---|---|---|
| Training Stress Score | TSS | `(dur × NP × IF) / (FTP × 3600) × 100` (power); HR- and pace-based variants otherwise | Physiological cost of a single workout |
| Chronic Training Load | CTL | 42-day EWMA of daily TSS | Long-term fitness |
| Acute Training Load | ATL | 7-day EWMA of daily TSS | Short-term fatigue |
| Training Stress Balance | TSB | `CTL − ATL` | Form |
| Recovery Score | REC | HRV and resting-HR z-scores vs 30-day baseline, blended with sleep score and prior-day load | Daily recovery (0–100) |
| Readiness Score | RDY | 70% recovery score + 30% TSB-based form (TSB only when no recovery score) | Daily readiness (0–100) |
| Strain Score | STR | Zone-weighted heart-rate minutes on a saturating scale | Cardiovascular load (0–100); day strain also counts minutes outside workouts |

---

## Documentation Index

| Document | Description |
|---|---|
| [SETUP.md](./docs/SETUP.md) | Local development setup and troubleshooting |
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | CI/CD, the reference production deployment, and self-hosting |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | System design and data flow |
| [TECH_STACK.md](./docs/TECH_STACK.md) | Technology choices |
| [DATA_MODELS.md](./docs/DATA_MODELS.md) | PostgreSQL schema, RLS policies, Pydantic models |
| [SCHEMA_TOOL.md](./docs/SCHEMA_TOOL.md) | Generating the schema snapshot in `docs/schema/` |
| [ALGORITHMS.md](./docs/ALGORITHMS.md) | TSS, CTL, ATL, TSB, recovery, strain |
| [AI_COACH.md](./docs/AI_COACH.md) | AI coach, prompts, memory, tools |
| [API_REFERENCE.md](./docs/API_REFERENCE.md) | API endpoints |
| [MOBILE.md](./docs/MOBILE.md) | SvelteKit app and Capacitor |
| [DESIGN_SYSTEM.md](./docs/DESIGN_SYSTEM.md) | Color tokens, typography, components |
| [GARMIN_INTEGRATION.md](./docs/GARMIN_INTEGRATION.md) | Garmin Connect integration |
| [STRAVA_INTEGRATION.md](./docs/STRAVA_INTEGRATION.md) | Strava OAuth, sync, and webhooks |
| [PUSH_NOTIFICATIONS.md](./docs/PUSH_NOTIFICATIONS.md) | FCM and web push |
| [REDIS.md](./docs/REDIS.md) | Redis caching and shared state |
| [RATE_LIMITING.md](./docs/RATE_LIMITING.md) | IP, AI, and per-action rate limits |
| [PERFORMANCE.md](./docs/PERFORMANCE.md) | Performance notes |
| [STREAM_STORAGE.md](./docs/STREAM_STORAGE.md) | How activity streams are stored |
| [PRIVACY_SETTINGS.md](./docs/PRIVACY_SETTINGS.md) | Privacy settings |
| [MCP_SERVER.md](./docs/MCP_SERVER.md) | Connect your data to Claude and other MCP clients |
| [PHOTON_MESSAGING.md](./docs/PHOTON_MESSAGING.md) | iMessage coach channel |
| [releases/](./docs/releases/) | Release notes |

---

## Quick Start

```bash
# 1. Clone and install root tooling (Supabase CLI)
git clone https://github.com/sbalbale/astraphe-ai-coach.git
cd astraphe-ai-coach
npm install
cp backend/.env.example backend/.env   # set APP_ENV=development, then Supabase keys
cp mobile/.env.example mobile/.env

# 2. Start local Supabase (applies all migrations on first start)
npx supabase start

# 3. Start Redis (optional)
docker compose up -d redis

# 4. Run backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 5. Run the app dev server
cd ../mobile && pnpm install && pnpm run dev
```

Full setup instructions → [docs/SETUP.md](./docs/SETUP.md). See [CONTRIBUTING.md](./CONTRIBUTING.md) for the contributor workflow.

---

## Third-Party API Access

None of the provider credentials are bundled with this repo:

- **Strava / WHOOP:** register your own developer application (self-serve) and put the client ID and secret in `backend/.env`.
- **Garmin:** the active integration logs in with each athlete's own Garmin Connect username and password (with MFA) through the community `garminconnect` library, so no developer credentials are needed. Garmin's official Connect Developer Program is partner-approval-only; the config keys for it are unused. See [docs/GARMIN_INTEGRATION.md](./docs/GARMIN_INTEGRATION.md).
- **intervals.icu:** each athlete connects with their own intervals.icu API key from the app.

Review each provider's terms before running a public-facing deployment.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the dev workflow and PR process, and [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for community guidelines. Found a security issue? See [SECURITY.md](./SECURITY.md) — please don't file it as a public issue.

---

## License

Licensed under the [Apache License 2.0](./LICENSE). Copyright © 2026 Sean Balbale.
