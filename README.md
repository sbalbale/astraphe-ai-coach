# APEX — AI Coaching Platform

> **Precision endurance coaching, powered by real-time physiological telemetry and Gemini AI.**

APEX is a multi-source, AI-driven health and fitness coaching platform that ingests data from Apple HealthKit, Garmin Connect, and WHOOP to deliver personalized, scientifically-grounded training recommendations through a conversational AI coach.

![Svelte](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-1.5_Pro-4285F4?logo=google&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white)
![Cloud Run](https://img.shields.io/badge/Google_Cloud-Run-4285F4?logo=googlecloud&logoColor=white)

---

## What APEX Does

APEX operates as an always-on performance intelligence layer between an athlete's wearable ecosystem and their training decisions.

**1. Aggregates physiological truth.**
Rather than trusting a single device, APEX ingests heart rate, HRV, sleep staging, GPS workouts, and power data from Apple HealthKit, Garmin Connect, and WHOOP — reconciling them into a single unified athlete state model updated in real time.

**2. Computes the metrics that matter.**
TSS, CTL, ATL, and TSB are computed server-side using NumPy-vectorized operations over rolling windows. Recovery and strain scores are derived from transparent, auditable weighted multi-factor models — not black-box device algorithms.

**3. Speaks like a coach, thinks like a physiologist.**
The APEX AI agent (Gemini 1.5 Pro) receives structured athletic context on every query — CTL, HRV trend, sleep debt, TSB position — and responds with concise, data-anchored recommendations. Every answer references at least one real number from the athlete's actual data.

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
│     APEX API (FastAPI · Cloud Run)      │
│     Stateless · Dockerized · Auto-scale │
└──────┬──────────────┬────────────┬──────┘
       │              │            │
  ┌────▼────┐  ┌──────▼──────┐  ┌─▼──────────────┐
  │ Gemini  │  │ Garmin API  │  │    Supabase     │
  │ 1.5 Pro │  │ WHOOP API   │  │ PostgreSQL      │
  │ RAG +   │  │ HealthKit   │  │ pgvector · RLS  │
  │ Fn Call │  │ (on-device) │  │ Realtime        │
  └─────────┘  └─────────────┘  └────────────────┘
```

---

## Repository Structure

```
apex-coach/
├── LICENSE
├── README.md                          ← This file
├── .env.example
├── .gitignore
├── .gitattributes
│
├── docs/                              ← Full documentation suite
│   ├── ARCHITECTURE.md
│   ├── TECH_STACK.md
│   ├── DATA_MODELS.md
│   ├── ALGORITHMS.md
│   ├── AI_COACH.md
│   ├── API_REFERENCE.md
│   ├── SETUP.md
│   ├── DEPLOYMENT.md
│   ├── DESIGN_SYSTEM.md
│   └── MOBILE.md
│
├── backend/                           ← FastAPI service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── cloudbuild.yaml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── routers/
│   │   │   ├── athlete.py
│   │   │   ├── workouts.py
│   │   │   ├── biometrics.py
│   │   │   ├── coach.py
│   │   │   ├── sync.py
│   │   │   └── plan.py
│   │   ├── services/
│   │   │   ├── algorithms.py          ← TSS, CTL, ATL, TSB, Recovery
│   │   │   ├── ai_coach.py            ← Gemini + RAG pipeline
│   │   │   ├── garmin.py
│   │   │   └── whoop.py
│   │   └── models/
│   │       ├── athlete.py
│   │       ├── workout.py
│   │       └── biometrics.py
│   ├── migrations/                    ← SQL migration files (source of truth)
│   │   ├── 00001_create_athletes.sql
│   │   ├── 00002_create_workouts.sql
│   │   ├── 00003_create_biometrics.sql
│   │   ├── 00004_create_tss_history.sql
│   │   ├── 00005_create_training_plans.sql
│   │   ├── 00006_create_oauth_tokens.sql
│   │   └── 00007_create_coach_memories.sql
│   ├── seeds/
│   │   └── dev_athlete.sql
│   └── tests/
│       ├── test_algorithms.py
│       ├── test_coach.py
│       ├── test_webhooks.py
│       └── conftest.py
│
├── mobile/                            ← Svelte 5 + Capacitor app
│   ├── capacitor.config.ts
│   ├── svelte.config.js
│   ├── package.json
│   ├── public/
│   │   ├── runner.js                  ← HealthKit background runner (native context)
│   │   └── background-runner-config.json
│   ├── src/
│   │   ├── app.html
│   │   ├── routes/
│   │   │   ├── +layout.svelte
│   │   │   ├── dashboard/+page.svelte
│   │   │   ├── training/+page.svelte
│   │   │   ├── plan/+page.svelte
│   │   │   ├── zones/+page.svelte
│   │   │   ├── recovery/+page.svelte
│   │   │   ├── sleep/+page.svelte
│   │   │   ├── strain/+page.svelte
│   │   │   ├── coach/+page.svelte
│   │   │   ├── connect/+page.svelte
│   │   │   └── profile/+page.svelte
│   │   └── lib/
│   │       ├── api/
│   │       │   ├── client.ts          ← Typed API client + SSE streaming
│   │       │   └── types.ts
│   │       ├── auth.ts
│   │       ├── healthkit.ts
│   │       ├── realtime.ts            ← Supabase Realtime subscriptions
│   │       ├── cache.ts               ← Offline-first TTL cache
│   │       ├── stores/
│   │       │   ├── athlete.svelte.ts  ← .svelte.ts required for runes
│   │       │   ├── conversation.svelte.ts
│   │       │   ├── workouts.svelte.ts
│   │       │   └── plan.svelte.ts
│   │       └── components/
│   │           ├── Card.svelte
│   │           ├── Tag.svelte
│   │           ├── Pill.svelte
│   │           ├── RadialProgress.svelte
│   │           ├── MetricBadge.svelte
│   │           ├── Nav.svelte
│   │           ├── Sidebar.svelte
│   │           └── charts/
│   │               ├── LineChart.svelte
│   │               ├── MultiLineChart.svelte
│   │               ├── DonutChart.svelte
│   │               └── BarChart.svelte
│   ├── ios/App/App/
│   │   ├── Info.plist
│   │   └── App.entitlements
│   └── android/app/src/main/
│       └── AndroidManifest.xml
│
└── supabase/
    ├── config.toml
    └── seed.sql
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
| [DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Cloud Run, Secret Manager, CI/CD pipeline, cost estimates |
| [DESIGN_SYSTEM.md](./docs/DESIGN_SYSTEM.md) | Spectral glassmorphism — color tokens, typography, components |
| [MOBILE.md](./docs/MOBILE.md) | Svelte 5 runes, Capacitor config, HealthKit background runner |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/seanbalbale/apex-coach.git
cd apex-coach
cp .env.example .env  # Fill in Supabase, Gemini, Garmin, WHOOP keys

# 2. Start local Supabase
supabase start && supabase db push

# 3. Run backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. Run mobile dev server
cd mobile && npm install && npm run dev
```

Full setup instructions → [SETUP.md](./SETUP.md)

---

## Important: Garmin API Access

Garmin gates their Connect API for enterprise use. A formal commercial application must be submitted to Garmin's developer program before production access is granted — this review typically takes **2–6 weeks**. Initiate this immediately at project start to avoid deployment delays. See [SETUP.md](./SETUP.md#7-garmin-api-access) for details.

---

## License

Copyright © 2026 Sean Balbale. All Rights Reserved. See [LICENSE](../LICENSE) for details.