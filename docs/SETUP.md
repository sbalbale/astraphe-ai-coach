# Setup Guide

How to run the full stack locally, from a fresh clone to a working app.

## What Runs Locally

| Piece | Technology | Default URL |
|---|---|---|
| Supabase API/Auth/Storage | Supabase CLI + Docker | `http://127.0.0.1:54321` |
| Supabase Studio | Supabase CLI + Docker | `http://127.0.0.1:54323` |
| Postgres | Supabase CLI + Docker | `127.0.0.1:54322` |
| Redis (optional) | Docker Compose | `redis://127.0.0.1:6379` |
| Backend API | FastAPI/Uvicorn | `http://localhost:8000` |
| Frontend | SvelteKit/Vite | `http://localhost:5173` |

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20+ | Root tooling and frontend build. |
| pnpm | 10+ | Required in `mobile/`; npm/yarn installs are blocked there by a preinstall check. |
| Python | 3.12 | Backend runtime (matches `backend/Dockerfile` and CI). |
| Docker | Current | Supabase local stack and Redis. On Windows, start Docker Desktop before Supabase. |
| Supabase CLI | Installed by root `npm install` | Run it as `npx supabase ...` from the repo root. |

## Install Root Tooling

From the repository root:

```bash
npm install
npx supabase --version
```

The root `package.json` also defines migration shortcuts:

| Script | Runs |
|---|---|
| `npm run supabase:migrate` | `supabase migration up --local --yes` (apply new migrations to the local stack) |
| `npm run supabase:migrate:linked` | `supabase migration up --linked --yes` |
| `npm run supabase:db:push` | `supabase db push --yes` (linked remote project) |

## Supabase Local Stack

Start Supabase (the first start applies every migration in `supabase/migrations/`):

```bash
npx supabase start
npx supabase status
```

Local ports from `supabase/config.toml`:

| Service | URL |
|---|---|
| API/Auth/Storage | `http://127.0.0.1:54321` |
| Postgres | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` |
| Studio | `http://127.0.0.1:54323` |
| Inbucket (test email) | `http://127.0.0.1:54324` |

Copy the API URL and keys from `supabase status` into the backend and mobile env files. Newer Supabase CLI versions label the keys **Publishable** and **Secret** instead of **anon** and **service_role**; they are the same keys. Use Publishable for `SUPABASE_KEY` / `VITE_SUPABASE_KEY` and Secret for `SUPABASE_SERVICE_ROLE_KEY`.

Apply migrations added after your first start:

```bash
npm run supabase:migrate
```

Or drop and rebuild the local database from scratch:

```bash
npx supabase db reset
```

`npx supabase db push` without `--local` targets a linked remote project, not the local stack. Without `supabase link` it fails with `Cannot find project ref`.

### Seed data

`supabase/config.toml` points seeding at `./seed.sql`, which does not exist, so `db reset` loads no seed data. To load the dev test athlete and 12 weeks of demo training data, run the seed files by hand, in this order:

```bash
docker exec -i supabase_db_astraphe-ai-coach psql -U postgres < supabase/seed_athlete.sql
docker exec -i supabase_db_astraphe-ai-coach psql -U postgres < supabase/seed_garmin_demo.sql
```

## Redis

Optional for local dev (the backend falls back to in-process caches and rate limits), but useful for matching production behaviour:

```bash
docker compose up -d redis
```

```env
REDIS_URL=redis://127.0.0.1:6379
```

## Backend

Create `backend/.env`:

```bash
cp backend/.env.example backend/.env
```

On Windows PowerShell:

```powershell
copy backend\.env.example backend\.env
```

Minimum local values:

```env
APP_ENV=development
APP_BASE_URL=http://localhost:8000
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_KEY=<anon / publishable key from supabase status>
SUPABASE_SERVICE_ROLE_KEY=<service_role / secret key from supabase status>
SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
GEMINI_API_KEY=<optional until using AI features>
```

`APP_ENV` defaults to `production` when unset. In production mode the API refuses to start without a valid `OAUTH_TOKEN_ENCRYPTION_KEY` and disables `/docs` and the debug router, so set `APP_ENV=development` locally.

Install and run:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -c "import fastapi, numpy; from google import genai; print('Dependencies OK')"
uvicorn app.main:app --reload --port 8000
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
.\dev.ps1   # uvicorn on port 8000 with timestamped logs (uvicorn-log-config.json)
```

Health check:

```bash
curl http://localhost:8000/health
```

Protected routes need a Supabase session JWT for a user with a matching `athletes.user_id` row.

Expected shape (`status` is `degraded` when Supabase is unreachable; `redis` is `unavailable` without Redis):

```json
{
  "status": "healthy",
  "service": "ASTRAPHE API",
  "version": "1.0.0",
  "redis": "connected",
  "supabase": "connected"
}
```

Backend tests run from the **repo root** (`pytest.ini` sets `testpaths = backend/tests` and `pythonpath = backend`). They ignore `backend/.env` and mock external calls, so no keys are needed:

```bash
python -m pytest
python -m pytest --cov=app   # with the 80% coverage gate from .coveragerc, as CI runs it
```

## Mobile/Web Frontend

Create `mobile/.env`:

```bash
cp mobile/.env.example mobile/.env
```

Set:

```env
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_KEY=<anon / publishable key from supabase status>
VITE_API_URL=http://localhost:8000
VITE_VAPID_PUBLIC_KEY=<optional web-push public key>
```

Install and run:

```bash
cd mobile
pnpm install
pnpm run dev
```

Open `http://localhost:5173`. Restart Vite after changing `mobile/.env`.

Other scripts:

| Command | Purpose |
|---|---|
| `pnpm run check` | `svelte-check` type checking |
| `pnpm run test` | Vitest |
| `pnpm run test:coverage` | Vitest with coverage thresholds (what CI runs) |
| `pnpm run build` | Static build into `mobile/build` |
| `pnpm run preview` | Preview the production build |
| `pnpm run icons` | Regenerate PWA icons |

Capacitor iOS:

```bash
pnpm run build
npx cap sync ios
npx cap open ios
```

There is no Android project in this repo yet. The HealthKit integration in `mobile/src/lib/integrations/health.ts` is a scaffold: it requests permissions but sends no HealthKit data yet.

## Integrations and Optional Settings

All settings and their defaults live in `backend/app/config.py`; `backend/.env.example` lists the common ones.

- AI: `LLM_PROVIDER` (`gemini` default, or `openai` for any OpenAI-compatible endpoint via `OPENAI_API_BASE_URL` / `OPENAI_API_KEY`), `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_ANALYSIS_MODEL`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_FREE_TIER`. Embeddings always use Gemini.
- Token encryption: `OAUTH_TOKEN_ENCRYPTION_KEY` (Fernet key; required in production, optional in dev).
- WHOOP: `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_WEBHOOK_SECRET` (should equal the client secret).
- Garmin: no keys needed for the active integration (athletes log in with their own Garmin credentials); `GARMIN_SYNC_POLL_HOURS` / `GARMIN_SYNC_POLL_MINUTES` set the poll interval. The `GARMIN_CONSUMER_*` keys are unused scaffolding.
- Strava: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_WEBHOOK_VERIFY_TOKEN`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID`.
- intervals.icu: `INTERVALS_ICU_API_BASE` (no default), `INTERVALS_ICU_AUTH_MODE`.
- Resend: `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`.
- Push: `FCM_SERVICE_ACCOUNT_JSON`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`.
- Coach web search: `SEARXNG_URL`.
- iMessage channel: `PHOTON_*` (see [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md)).
- Background work: `BACKGROUND_LOOPS_ENABLED`, `NOTIFICATION_SCHEDULER_ENABLED`.

Use ngrok or Cloudflare Tunnel when testing OAuth callbacks or webhooks against a local backend.

## Smoke Test

With Supabase, the backend and the frontend running:

1. Sign up or sign in through the app.
2. Confirm an `athletes` row exists for the Supabase auth user (Studio, `athletes` table).
3. Check `GET /health`.
4. Load the Dashboard, Profile and Training screens.

## Common Problems

**Supabase will not start.** Restart Docker, check that ports `54320`-`54324` are free, then run `npx supabase status` and copy the printed URLs and keys into the env files.

**Backend cannot reach Supabase.** `SUPABASE_URL` must be the API URL from `supabase status`, `SUPABASE_KEY` the anon/publishable key and `SUPABASE_SERVICE_ROLE_KEY` the service_role/secret key.

**Frontend auth or API calls fail.** Check `VITE_SUPABASE_URL`, `VITE_SUPABASE_KEY` and `VITE_API_URL`, then restart Vite. With `APP_ENV` other than `production`, backend CORS (`backend/app/main.py`) allows `localhost:5173`, `localhost:4173`, `127.0.0.1:5173` and LAN IPs (`192.168.x.x`, `10.x.x.x`).

**Athlete profile not found.** The token is valid but no `athletes` row matches the auth user's id. Create the row, or load the [seed data](#seed-data).

## Project Structure

```text
backend/
  app/
    main.py
    config.py
    dependencies.py
    core/
    models/
    prompts/
    routers/
    services/
  scripts/
  tests/
  Dockerfile
  dev.ps1
  requirements.txt

mobile/
  src/routes/
  src/lib/
  src/service-worker.ts
  scripts/
  capacitor.config.ts
  firebase.json
  package.json

mcp-server/
photon-bridge/

supabase/
  migrations/
  templates/
  config.toml
  seed_athlete.sql
  seed_garmin_demo.sql
```
