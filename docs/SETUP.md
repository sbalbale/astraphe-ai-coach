# Setup Guide

This is the short local setup checklist. For more detail, see `docs/GETTING_STARTED.md`.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20+ | Root tooling and frontend build. |
| pnpm | 10+ | Required in `mobile/`; npm/yarn installs are blocked there. |
| Python | 3.12 | Backend runtime. |
| Docker | Current | Supabase local stack and Redis. |
| Supabase CLI | Project-local or global | Prefer `npx supabase ...` from repo root. |

## Install Root Tooling

From the repository root:

```bash
npm install
npx supabase --version
```

## Supabase Local Stack

Start Supabase:

```bash
npx supabase start
npx supabase status
```

Current local ports come from `supabase/config.toml`:

| Service | URL |
|---|---|
| API/Auth/Storage | `http://127.0.0.1:54321` |
| Postgres | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` |
| Studio | `http://127.0.0.1:54323` |
| Inbucket | `http://127.0.0.1:54324` |

Apply migrations:

```bash
npx supabase db push
```

Reset and seed a clean database:

```bash
npx supabase db reset
```

Note: `supabase/config.toml` currently points seed loading at `./seed.sql`. The repo also contains `supabase/seed_athlete.sql`; keep the config and seed file aligned before relying on automatic seeding.

## Redis

Optional for single-process local dev, but useful for matching production rate-limit/cache behavior:

```bash
docker compose up -d redis
```

Use:

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
SUPABASE_KEY=<anon key from supabase status>
SUPABASE_SERVICE_ROLE_KEY=<service_role key from supabase status>
SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
GEMINI_API_KEY=<optional until using AI features>
```

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

Windows activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

Health check:

```bash
curl http://localhost:8000/health
```

Expected shape:

```json
{
  "status": "healthy",
  "service": "ASTRAPHE API",
  "version": "1.0.0",
  "redis": "connected",
  "supabase": "connected"
}
```

Backend tests:

```bash
cd backend
python -m pytest tests -v
```

## Mobile/Web Frontend

Create `mobile/.env`:

```bash
cp mobile/.env.example mobile/.env
```

Set:

```env
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_KEY=<anon key from supabase status>
VITE_API_URL=http://localhost:8000
VITE_VAPID_PUBLIC_KEY=<optional web-push public key>
```

Install and run:

```bash
cd mobile
pnpm install
pnpm run dev
```

Quality commands:

```bash
pnpm run check
pnpm run test
```

Build:

```bash
pnpm run build
```

Capacitor iOS:

```bash
pnpm run build
npx cap sync ios
npx cap open ios
```

Android is not currently scaffolded in this repo.

## Integrations

Optional backend env values are documented in `backend/.env.example`:

- WHOOP: `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, optional `WHOOP_WEBHOOK_SECRET`.
- Garmin: `GARMIN_CONSUMER_KEY`, `GARMIN_CONSUMER_SECRET`, `GARMIN_WEBHOOK_SECRET`.
- Strava: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_WEBHOOK_VERIFY_TOKEN`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID`.
- Resend: `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`.
- Push: `FCM_SERVICE_ACCOUNT_JSON`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`.

Use ngrok or Cloudflare Tunnel when testing OAuth callbacks/webhooks against a local backend.

## Project Structure

```text
backend/
  app/
    main.py
    config.py
    dependencies.py
    routers/
    services/
    models/
  tests/
  Dockerfile
  requirements.txt

mobile/
  src/routes/
  src/lib/
  src/service-worker.ts
  capacitor.config.ts
  firebase.json
  package.json

supabase/
  migrations/
  config.toml
  seed_athlete.sql
```
