# Tech Stack

## Summary

ASTRAPHE is a SvelteKit/Svelte 5 frontend, FastAPI Python backend, Supabase data/auth/storage layer, Redis-assisted cache/rate-limit layer, and Google GenAI-powered coaching system.

## Frontend

The frontend lives in `mobile/` and is a static SvelteKit SPA/PWA with Capacitor iOS support.

Key package versions from `mobile/package.json`:

| Package | Version | Purpose |
|---|---:|---|
| `svelte` | `5.55.5` | UI framework |
| `@sveltejs/kit` | `2.58.0` | Routing/app framework |
| `vite` | `8.0.10` | Dev/build tool |
| `typescript` | `6.0.3` | Type checking |
| `tailwindcss` | `3.4.19` | Styling |
| `@capacitor/core` | `8.3.1` | Native bridge |
| `@capacitor/ios` | `8.3.1` | iOS target |
| `@capacitor/push-notifications` | `8.1.0` | Native push scaffold |
| `@interval-health/capacitor-health` | `2.0.0` | HealthKit scaffold |
| `@supabase/supabase-js` | `2.105.0` | Auth/client SDK |
| `layerchart` | `1.0.13` | Svelte chart primitives |
| `d3` | `7.9.0` | Scales and visualization utilities |
| `maplibre-gl` | `5.24.0` | Map rendering |
| `vite-plugin-pwa` | `1.3.0` | PWA/service worker |
| `workbox-*` | `7.4.1` | PWA caching/routing |

The frontend package requires pnpm 10+. Android is not currently scaffolded.

## Backend

The backend lives in `backend/`.

Key choices:

| Technology | Purpose |
|---|---|
| Python 3.12 | Runtime |
| FastAPI | HTTP API |
| Pydantic v2 / pydantic-settings | Validation and config |
| NumPy | TSS, CTL, ATL, TSB, recovery, strain calculations |
| Supabase Python client | PostgREST/Auth/Storage access |
| httpx | Third-party HTTP calls |
| google-genai | Coach, analysis, embeddings, grounding |
| redis-py asyncio | Redis rate-limit/cache client |
| pywebpush | Web push notifications |
| firebase-admin | Native push notifications |
| pytest | Backend tests |

The backend is stateless; shared state lives in Supabase and Redis.

## AI

Defaults from `backend/app/config.py`:

| Setting | Default | Role |
|---|---|---|
| `GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Coach chat |
| `GEMINI_ANALYSIS_MODEL` | `gemini-flash-lite-latest` | Screen insights |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Coach memory embeddings |

The coach uses:

- prompt file: `backend/app/prompts/coach_behavior.md`
- Google GenAI SDK: `from google import genai`
- custom function tools in `backend/app/services/coach_tools.py`
- Google Search grounding
- pgvector memories in `coach_memories`
- cached screen analysis in `athlete_analyses`

Do not document the old Gemini Pro-era coach model as the current model.

## Data Layer

Supabase provides:

- PostgreSQL
- Auth
- Row Level Security
- Storage
- pgvector
- local development stack through Supabase CLI/Docker

The authoritative schema history is `supabase/migrations/`.

Important tables include:

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

## Redis

Redis is optional locally and recommended in production.

It backs:

- global per-IP rate limiting
- per-athlete AI rate limiting
- activity stream caching
- workout zone caching

If Redis is unavailable, rate limiting falls back to process-local memory.

## Integrations

| Integration | Current Role |
|---|---|
| Supabase Auth | User identity and JWTs. |
| Supabase Storage | Coach uploads and other app storage buckets. |
| Strava | OAuth, webhooks, backfill, activity detail, streams, laps. |
| WHOOP | OAuth, webhooks, recovery/sleep/strain backfill. |
| Garmin | Webhook ingestion and OAuth-related configuration. |
| Resend | Marketing privacy opt-in sync. |
| Firebase/FCM | Native push notification transport. |
| Web Push/VAPID | PWA push notification transport. |
| Cloudflare Tunnel | Deploy-time SSH path to Proxmox. |
| Firebase Hosting | Static frontend hosting. |
| GHCR | Backend container registry. |

## Deployment

Current repo automation:

- Backend: `.github/workflows/deploy.yml` builds `ghcr.io/sbalbale/astraphe-api`, deploys to Proxmox over Cloudflare Access SSH, and runs migrations in the remote database container.
- Frontend: Firebase Hosting workflows build `mobile/` with pnpm and deploy live/preview channels.

`backend/cloudbuild.yaml` remains in the repo as an alternate/historical Cloud Run build pipeline and should not be described as the primary deployment path unless it is reactivated.

## Local Commands

Root:

```bash
npm install
npx supabase start
npx supabase db push
docker compose up -d redis
```

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
python -m pytest tests -v
```

Mobile:

```bash
cd mobile
pnpm install
pnpm run dev
pnpm run check
pnpm run test
pnpm run build
```
