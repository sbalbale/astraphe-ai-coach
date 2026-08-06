# Getting Started

This guide explains the local development stack. For the compact checklist, see `docs/SETUP.md`.

## What Runs Locally

| Piece | Technology | Default URL |
|---|---|---|
| Supabase API/Auth/Storage | Supabase CLI + Docker | `http://127.0.0.1:54321` |
| Supabase Studio | Supabase CLI + Docker | `http://127.0.0.1:54323` |
| Postgres | Supabase CLI + Docker | `127.0.0.1:54322` |
| Redis | Docker Compose | `redis://127.0.0.1:6379` |
| Backend API | FastAPI/Uvicorn | `http://127.0.0.1:8000` |
| Frontend | SvelteKit/Vite | `http://127.0.0.1:5173` |

The Supabase ports are the standard local CLI ports configured in `supabase/config.toml`.

## 1. Install Prerequisites

Required:

- Git
- Docker Desktop or Docker Engine
- Node.js 20+
- pnpm 10+
- Python 3.12
- Supabase CLI, either through root `npm install` and `npx supabase`, or globally

Windows users should run commands from PowerShell or Windows Terminal and make sure Docker Desktop is running before starting Supabase.

## 2. Install Root Dependencies

From the repository root:

```bash
npm install
npx supabase --version
```

## 3. Start Supabase

```bash
npx supabase start
npx supabase status
```

Copy the printed API URL and keys into the backend and mobile env files. Recent
Supabase CLI versions print keys labeled **Publishable** / **Secret** instead
of the older **anon** / **service_role** naming — they're the same two keys
under new names; use Publishable for `SUPABASE_KEY` / `VITE_SUPABASE_KEY` and
Secret for `SUPABASE_SERVICE_ROLE_KEY`.

Apply new migration files to your **local** stack:

```bash
npx supabase db reset
```

This drops and recreates the local database, re-running every migration in
`supabase/migrations/` plus the seed. It's the command you want for ordinary
local development — **`supabase db push` targets a linked remote project**
(`supabase link`) and will fail with `Cannot find project ref. Have you run
supabase link?` if you haven't set one up, which most local-only setups won't
have.

`supabase/config.toml` currently has:

```toml
[db.seed]
enabled = true
sql_paths = ["./seed.sql"]
```

The repo also contains `supabase/seed_athlete.sql`. Align the configured path with the seed file you intend to use before relying on automatic seed loading.

## 4. Start Redis

Redis is optional but recommended:

```bash
docker compose up -d redis
```

Use `REDIS_URL=redis://127.0.0.1:6379` in `backend/.env`.

## 5. Backend Environment

Create:

```bash
cp backend/.env.example backend/.env
```

Windows:

```powershell
copy backend\.env.example backend\.env
```

Minimum local backend values:

```env
APP_ENV=development
APP_BASE_URL=http://localhost:8000
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service_role key>
SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
REDIS_URL=redis://127.0.0.1:6379
GEMINI_API_KEY=<optional for non-AI smoke tests>
```

Important names:

- Backend uses `SUPABASE_KEY` for the anon/public key.
- Mobile uses `VITE_SUPABASE_KEY`.
- AI defaults are `GEMINI_MODEL`, `GEMINI_ANALYSIS_MODEL`, and `GEMINI_EMBEDDING_MODEL`.

## 6. Run The Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Windows:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl http://127.0.0.1:8000/health
```

Protected routes require a Supabase session JWT for a user with a matching `athletes.user_id`.

## 7. Mobile/Web Environment

Create:

```bash
cp mobile/.env.example mobile/.env
```

Set:

```env
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_KEY=<anon key>
VITE_API_URL=http://127.0.0.1:8000
VITE_VAPID_PUBLIC_KEY=<optional web push key>
```

Restart Vite after changing `mobile/.env`.

## 8. Run The Frontend

The `mobile/` package requires pnpm.

```bash
cd mobile
pnpm install
pnpm run dev
```

Open the URL Vite prints, usually `http://127.0.0.1:5173`.

Quality checks:

```bash
pnpm run check
pnpm run test
```

Build:

```bash
pnpm run build
```

## 9. Capacitor iOS

The current native scaffold is iOS only.

```bash
cd mobile
pnpm run build
npx cap sync ios
npx cap open ios
```

The HealthKit integration is currently scaffolded through `mobile/src/lib/integrations/health.ts`; it does not yet perform full native HealthKit ingestion.

## 10. Smoke Test

With Supabase, Redis, backend, and frontend running:

1. Sign up or sign in through the app.
2. Confirm an `athletes` row exists for the Supabase auth user.
3. Check `GET /health`.
4. Load Dashboard/Profile/Training screens.
5. Test a protected endpoint with a valid access token.

Example:

```bash
curl http://127.0.0.1:8000/health
```

Expected response includes `status`, `service`, `version`, `redis`, and `supabase`.

## 11. Tests

Backend:

```bash
cd backend
python -m pytest tests -v
```

Mobile:

```bash
cd mobile
pnpm run check
pnpm run test
```

## 12. Common Problems

### Supabase Will Not Start

- Restart Docker.
- Check whether ports `54320-54324` are already in use.
- Run `npx supabase status` and copy the actual printed URLs into env files.

### Backend Cannot Reach Supabase

- Ensure `SUPABASE_URL` is the API URL from `supabase status`.
- Ensure `SUPABASE_KEY` is the anon key and `SUPABASE_SERVICE_ROLE_KEY` is the service role key.

### Frontend Auth Or API Calls Fail

- Ensure `VITE_SUPABASE_URL`, `VITE_SUPABASE_KEY`, and `VITE_API_URL` are set.
- Restart the Vite dev server.
- Confirm backend CORS allows your local origin.

### Athlete Profile Not Found

The token is valid, but no `athletes` row matches `auth.users.id`. Create the athlete row or reset/seed the local database.

## 13. Useful References

- `docs/API_REFERENCE.md`
- `docs/ARCHITECTURE.md`
- `docs/MOBILE.md`
- `docs/DATA_MODELS.md`
- `docs/DEPLOYMENT.md`
- `docs/STRAVA_INTEGRATION.md`
- `docs/PUSH_NOTIFICATIONS.md`
