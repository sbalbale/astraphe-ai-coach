# ASTRAPHE — AI Coaching Platform

> **Precision endurance coaching, powered by real-time physiological telemetry and Gemini AI.**

ASTRAPHE is a multi-source, AI-driven health and fitness coaching platform that ingests data from Apple HealthKit, Garmin Connect, and WHOOP to deliver personalized, scientifically-grounded training recommendations through a conversational AI coach.

![Svelte](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-AI-886FBF?logo=googlegemini&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white)
![License](https://img.shields.io/badge/License-Apache_2.0-blue)

---

## What ASTRAPHE Does

ASTRAPHE operates as an always-on performance intelligence layer between an athlete's wearable ecosystem and their training decisions.

**1. Aggregates physiological truth.**
Rather than trusting a single device, ASTRAPHE ingests heart rate, HRV, sleep staging, GPS workouts, and power data from Apple HealthKit, Garmin Connect, and WHOOP — reconciling them into a single unified athlete state model updated in real time.

**2. Computes the metrics that matter.**
TSS, CTL, ATL, and TSB are computed server-side using NumPy-vectorized operations over rolling windows. Recovery and strain scores are derived from transparent, auditable weighted multi-factor models — not black-box device algorithms.

**3. Speaks like a coach, thinks like a physiologist.**
The ASTRAPHE AI agent receives structured athletic context on every query — CTL, HRV trend, sleep debt, TSB position — and responds with concise, data-anchored recommendations. Every answer references at least one real number from the athlete's actual data.

---

## Architecture

```
┌─────────────────────────────────────────┐
│     Mobile App (Svelte 5 + Capacitor)   │
│     iOS · Android                       │
│     LayerChart / D3 SVG visualizations  │
└────────────────┬────────────────────────┘
                 │ HTTPS / SSE
┌────────────────▼────────────────────────┐
│     ASTRAPHE API (FastAPI · Dockerized)  │
│     Stateless · deploy anywhere you like │
└──────┬──────────────┬────────────┬──────┘
       │              │            │
  ┌────▼────┐  ┌──────▼──────┐  ┌─▼──────────────┐
  │         │  │ Garmin API  │  │    Supabase    │
  │         │  │ WHOOP API   │  │ PostgreSQL     │
  │ RAG +   │  │ HealthKit   │  │ pgvector · RLS │
  │ Fn Call │  │ (on-device) │  │ Realtime       │
  └─────────┘  └─────────────┘  └────────────────┘
```

---

## Repository Structure

```
astraphe-ai-coach/
├── LICENSE
├── README.md                 ← This file
├── .env.example               ← Pointer to backend/mobile .env.example files
├── docker-compose.yml          ← Local Redis for dev
│
├── docs/                       ← Full documentation suite (see index below)
│
├── backend/                    ← FastAPI service (Python 3.12)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py           ← pydantic-settings, reads backend/.env
│   │   ├── dependencies.py     ← auth, rate limiting
│   │   ├── core/
│   │   ├── models/             ← Pydantic schemas
│   │   ├── prompts/             ← AI coach system prompts
│   │   ├── routers/            ← API endpoints
│   │   └── services/            ← algorithms, Strava/WHOOP/Garmin sync, AI coach
│   ├── scripts/                ← one-off ops/maintenance scripts
│   └── tests/                  ← pytest suite
│
├── mobile/                     ← Svelte 5 + SvelteKit + Capacitor (iOS)
│   ├── capacitor.config.ts
│   ├── src/
│   │   ├── routes/             ← SvelteKit pages
│   │   └── lib/                ← api client, stores, components, utils
│   └── ios/                    ← native iOS project (Android not yet scaffolded)
│
└── supabase/                   ← Postgres schema (source of truth)
    ├── config.toml
    ├── migrations/              ← SQL migrations, RLS policies
    ├── functions/               ← Edge functions
    └── seed_athlete.sql         ← Dev seed data
```

---

## Core Metrics

| Metric | Abbr | Formula | Description |
|---|---|---|---|
| Training Stress Score | TSS | `(dur × NP × IF) / (FTP × 3600) × 100` | Physiological cost of a single workout |
| Chronic Training Load | CTL | 42-day EWMA of TSS | Long-term fitness |
| Acute Training Load | ATL | 7-day EWMA of TSS | Short-term fatigue |
| Training Stress Balance | TSB | `CTL(yesterday) − ATL(yesterday)` | Form / race readiness |
| Readiness Score | RDY | Weighted: HRV 35%, Sleep 30%, RHR 20%, Load 10%, Vitals 5% | Daily readiness (0–100) |
| Strain Score | STR | Zone-weighted cardiovascular load | Cardiovascular stress (0–21) |

---

## Documentation Index

| Document | Description |
|---|---|
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | System design, service topology, full data flow diagrams |
| [TECH_STACK.md](./docs/TECH_STACK.md) | Technology choices and decision rationale |
| [DATA_MODELS.md](./docs/DATA_MODELS.md) | PostgreSQL schema, RLS policies, Pydantic models |
| [ALGORITHMS.md](./docs/ALGORITHMS.md) | TSS, CTL, ATL, TSB, Recovery Score — full Python implementations |
| [AI_COACH.md](./docs/AI_COACH.md) | Gemini integration, system prompt, RAG pipeline, function calling |
| [API_REFERENCE.md](./docs/API_REFERENCE.md) | All FastAPI endpoints with request/response shapes |
| [SETUP.md](./docs/SETUP.md) | Local development environment setup across all three services |
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | How the reference instance is deployed, plus a generic self-host guide |
| [DESIGN_SYSTEM.md](./docs/DESIGN_SYSTEM.md) | Spectral glassmorphism — color tokens, typography, components |
| [MOBILE.md](./docs/MOBILE.md) | Svelte 5 runes, Capacitor config, HealthKit background runner |
| [STRAVA_INTEGRATION.md](./docs/STRAVA_INTEGRATION.md) | Strava OAuth, sync, and webhook setup |
| [GARMIN_INTEGRATION.md](./docs/GARMIN_INTEGRATION.md) | Garmin Connect integration and API access notes |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/sbalbale/astraphe-ai-coach.git
cd astraphe-ai-coach
cp backend/.env.example backend/.env   # Fill in Supabase, Gemini, Strava/WHOOP keys
cp mobile/.env.example mobile/.env

# 2. Start local Supabase
npx supabase start && npx supabase db push

# 3. Run backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. Run mobile dev server
cd mobile && pnpm install && pnpm run dev
```

Full setup instructions → [docs/SETUP.md](./docs/SETUP.md). See [CONTRIBUTING.md](./CONTRIBUTING.md) for the contributor workflow.

---

## Important: Third-Party API Access

This app integrates with Strava, WHOOP, and Garmin. Each requires **your own** developer application and credentials — none are bundled with this repo:

- **Strava / WHOOP:** self-serve developer registration, usually approved instantly.
- **Garmin:** gates their Connect API for enterprise use — a formal commercial application must be submitted to Garmin's developer program before production access is granted, typically taking **2–6 weeks**. Initiate this early if you need Garmin support.

Review each provider's developer terms before running a public-facing deployment — see [docs/SETUP.md](./docs/SETUP.md) for registration details.

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for the dev workflow, code style, and PR process, and [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for community guidelines. Found a security issue? See [SECURITY.md](./SECURITY.md) — please don't file it as a public issue.

---

## License

Licensed under the [Apache License 2.0](./LICENSE). Copyright © 2026 Sean Balbale.

