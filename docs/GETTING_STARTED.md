# Getting started — local development

This guide walks through everything you need to run **ASTRAPE** on your machine: **Docker** (for Supabase), the **Supabase CLI**, **PostgreSQL schema** (migrations + seed), the **Python/FastAPI backend** (virtual environment), and the **SvelteKit mobile/web frontend** (Node.js). It also covers **environment variables**, how the pieces talk to each other, and optional tools for integrations and deployment.

For a shorter checklist, see [SETUP.md](./SETUP.md). This document is the long-form companion with more context and troubleshooting.

---

## What you are running locally

| Piece | Technology | Typical URL / port |
|--------|------------|---------------------|
| Database + Auth + Storage + Realtime | Supabase (Docker) | API: `http://127.0.0.1:57321` (see note below) |
| Admin UI | Supabase Studio | `http://127.0.0.1:57323` |
| Backend API | FastAPI + Uvicorn | `http://127.0.0.1:8000` |
| Frontend | SvelteKit + Vite | `http://127.0.0.1:5173` (Vite default) |

**Important — non-default Supabase ports:** This repo’s [`supabase/config.toml`](../supabase/config.toml) sets custom ports so they do not clash with other projects. Local defaults are:

- **REST / Auth API:** `57321` (not `54321`)
- **PostgreSQL:** `57322` (not `54322`)
- **Studio:** `57323`
- **Inbucket (email catcher):** `57324`

Always run `supabase status` after `supabase start` and copy the printed URLs and keys into your `.env` files.

---

## 1. Prerequisites

Install these **before** cloning if you do not already have them.

### Required

| Tool | Version / notes | Why you need it |
|------|-----------------|-----------------|
| **Git** | Any recent | Clone the repository |
| **Docker Desktop** | Current stable | Supabase local stack runs in containers |
| **Node.js** | **20.x LTS** or newer | SvelteKit, Vite, npm, Supabase CLI (if installed via npm) |
| **Python** | **3.12.x** (matches [`backend/Dockerfile`](../backend/Dockerfile)) | FastAPI backend |
| **Supabase CLI** | Latest | `supabase start`, migrations, local status |

**Windows notes**

- Install **Docker Desktop** and ensure it is running (whale icon stable) before `supabase start`.
- Docker Desktop often recommends **WSL 2** as the backend; that setup is well supported for Supabase.
- Use **PowerShell** or **Windows Terminal** for the commands below unless you prefer Git Bash.

**macOS / Linux notes**

- On Linux, use Docker Engine + Compose plugin instead of Docker Desktop if you prefer; Supabase documents both paths.

### How to install the Supabase CLI

Pick **one** approach:

**A — Project-local CLI (recommended, matches repo)**

From the **repository root** (where the root [`package.json`](../package.json) lives):

```bash
npm install
```

That installs the `supabase` package as a dev dependency. Run the CLI with **`npx`** so you always use the project’s version:

```bash
npx supabase --version
npx supabase start
```

**B — Global install**

```bash
npm install -g supabase
supabase --version
```

### Optional but useful

| Tool | Use |
|------|-----|
| **Google Cloud SDK** | Deployments and GCP resources — see [DEPLOYMENT.md](./DEPLOYMENT.md) |
| **ngrok** (or Cloudflare Tunnel) | Expose `localhost:8000` for Garmin / WHOOP / Strava webhooks during development |
| **curl** or **HTTPie** | Hit `/health` and API routes from the terminal |

---

## 2. Clone the repository

```bash
git clone https://github.com/seanbalbale/astrape-coach.git
cd astrape-coach
```

(Use your fork URL if you develop on a fork.)

---

## 3. Supabase local stack

All commands in this section are run from the **repository root** (`astrape-coach/`), where the `supabase/` directory lives.

### 3.1 Start Supabase

Ensure **Docker Desktop** (or your Docker daemon) is running, then:

```bash
npx supabase start
```

The first run downloads images and can take several minutes.

### 3.2 Read `supabase status` and save keys

```bash
npx supabase status
```

You will see **API URL**, **anon key**, **service_role key**, **DB URL**, **Studio URL**, etc. You will paste the URL and keys into env files in the next sections.

- **Anon key** → used by the mobile app and as `SUPABASE_KEY` for the backend’s default Supabase client.
- **Service role key** → `SUPABASE_SERVICE_ROLE_KEY` in the backend for admin operations (bypasses RLS); keep it secret and never ship it to the client.

### 3.3 Apply migrations

Migrations live in [`supabase/migrations/`](../supabase/migrations/).

On first **`supabase start`**, the CLI typically applies all files in `supabase/migrations/`. When you **add or change** migrations, apply them to the local database with:

```bash
npx supabase db push
```

The root [`package.json`](../package.json) also defines:

```bash
npm run supabase:db:push
```

(equivalent to `supabase db push --yes` using the project’s installed CLI.)

### 3.4 Seed data

[`supabase/config.toml`](../supabase/config.toml) enables seeds and points at [`supabase/seed_athlete.sql`](../supabase/seed_athlete.sql).

**Seeding runs when you reset the local database**, not on every `start`. For a **fresh** local DB with migrations + seed:

```bash
npx supabase db reset
```

**Warning:** `db reset` **drops** local Postgres data in this Supabase project, then reapplies migrations and runs the seed SQL. Use it when you want a clean slate; avoid it if you have local data you need to keep.

Alternative: open **Supabase Studio** → **SQL Editor** and run portions of `seed_athlete.sql` manually.

### 3.5 Verify

- Open **Studio:** `http://127.0.0.1:57323` (per this repo’s config).
- Confirm tables exist under **Table Editor** after migrations.
- Optional: connect with `psql` using the **DB URL** from `supabase status`.

---

## 4. Environment variables

ASTRAPE uses **two** primary env locations:

| Location | Used by |
|----------|---------|
| [`backend/.env.example`](../backend/.env.example) → copy to `backend/.env` | FastAPI / Uvicorn |
| [`mobile/.env.example`](../mobile/.env.example) → copy to `mobile/.env` | SvelteKit (Vite) — variables must be prefixed with `VITE_` |

The repository root [`.env.example`](../.env.example) may be empty; treat **`backend/.env`** and **`mobile/.env`** as the source of truth for local development.

### 4.1 Backend (`backend/.env`)

From the repo root:

```bash
copy backend\.env.example backend\.env
```

On macOS/Linux:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at minimum:

**Supabase (from `npx supabase status`)**

- `SUPABASE_URL` — e.g. `http://127.0.0.1:57321` (use the exact **API URL** printed by the CLI).
- `SUPABASE_KEY` — the **anon** `public` key (the backend code uses this name, not `SUPABASE_ANON_KEY`).
- `SUPABASE_SERVICE_ROLE_KEY` — the **service_role** key (required for code paths that use `get_admin_db()`).

**App URLs**

- `APP_BASE_URL` — `http://127.0.0.1:8000` for local API.
- `APP_ENV` — `development`.

**AI**

- `GEMINI_API_KEY` — from [Google AI Studio](https://aistudio.google.com/) (or your Google Cloud project). Coach and analysis features need a valid key.

**Integrations (optional for first run)**

- WHOOP, Garmin, Strava blocks in the example file can stay placeholders until you test those flows. Webhooks need a public URL (ngrok, etc.); see [SETUP.md](./SETUP.md#7-garmin-api-access) and [STRAVA_INTEGRATION.md](./STRAVA_INTEGRATION.md) if applicable.

**Optional local debugging**

- `TEST_ATHLETE_ID` — only for controlled local use; see [`backend/app/dependencies.py`](../backend/app/dependencies.py). Do not rely on this in shared or production environments.

Settings are loaded by [`backend/app/config.py`](../backend/app/config.py) via **pydantic-settings** from `backend/.env` when you run Uvicorn from the `backend/` directory.

### 4.2 Frontend (`mobile/.env`)

```bash
copy mobile\.env.example mobile\.env
```

macOS/Linux:

```bash
cp mobile/.env.example mobile/.env
```

Set:

- `VITE_SUPABASE_URL` — same API URL as backend `SUPABASE_URL`.
- `VITE_SUPABASE_KEY` — same **anon** key as backend `SUPABASE_KEY`.
- `VITE_API_URL` — `http://127.0.0.1:8000` so the app calls your local FastAPI server.

Restart `npm run dev` after any change to `mobile/.env`.

---

## 5. Python backend (virtual environment)

### 5.1 Create and activate `.venv`

From the repository root:

```bash
cd backend
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

If execution policy blocks activation:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Windows (cmd):**

```cmd
.venv\Scripts\activate.bat
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 5.2 Install dependencies

Still inside `backend/` with the venv activated:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5.3 Quick sanity check

```bash
python -c "import fastapi, numpy; print('OK')"
```

### 5.4 Run the API

From **`backend/`** (so `app.main:app` resolves and `.env` is found):

```bash
uvicorn app.main:app --reload --port 8000
```

- API base: `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`
- Health: `GET http://127.0.0.1:8000/health` → JSON like `{"status": "healthy", "service": "ASTRAPE API"}`

Protected routes expect a **Supabase JWT** (`Authorization: Bearer …`) from a signed-in user whose `auth.users` row matches an **`athletes`** row. Use the mobile app sign-up/sign-in flow, or Studio **Authentication** to create a user and align seed data / `user_id` as needed.

---

## 6. SvelteKit frontend (`mobile/`)

The “mobile” app is **Svelte 5** + **SvelteKit** + **Vite**, with **Capacitor** for native iOS (see [MOBILE.md](./MOBILE.md)).

### 6.1 Install Node dependencies

```bash
cd mobile
npm install
```

This installs SvelteKit, Svelte 5, Capacitor, Tailwind, Supabase JS client, etc., per [`mobile/package.json`](../mobile/package.json).

### 6.2 Capacitor sync (optional for pure web dev)

For device/simulator builds you will need:

```bash
npx cap sync
```

For **browser-only** local development, `npm run dev` is often enough.

### 6.3 Run the dev server

```bash
npm run dev
```

Open the URL Vite prints (usually `http://127.0.0.1:5173`). Ensure **`mobile/.env`** points at local Supabase and API URLs.

### 6.4 Quality commands

```bash
npm run check
npm run test
```

### 6.5 Native iOS (optional)

Requires **Xcode** on macOS:

```bash
npm run build
npx cap sync ios
npx cap open ios
```

Then run from Xcode. Android scaffolding is not present in all clones; follow [MOBILE.md](./MOBILE.md) if you add Android.

---

## 7. End-to-end smoke test

With **Supabase running**, **backend** on port **8000**, and **frontend** on **5173**:

1. Open the app in the browser, sign up or sign in (Supabase Auth).
2. Confirm you can load screens that read from Supabase and the API.
3. From a terminal, verify the API process:

```bash
curl -s http://127.0.0.1:8000/health
```

Expect a JSON body with `"status": "healthy"`.

For protected routes, use a valid **Supabase session JWT** in `Authorization: Bearer …` (for example from the signed-in app or Supabase Studio). If you get **401** or **404 athlete**, the token is missing, expired, or there is no matching **`athletes`** row for that **`user_id`**.

---

## 8. Tests (backend)

From `backend/` with `.venv` activated:

```bash
pytest tests/ -v
```

Focused suites:

```bash
pytest tests/test_algorithms.py -v
pytest tests/test_coach.py -v
pytest tests/test_webhooks.py -v
```

---

## 9. Common problems

### Docker / Supabase will not start

- Fully quit and restart Docker Desktop.
- Ensure no other stack is bound to **57321–57324** (or edit `supabase/config.toml` and use new ports, then update all `.env` files).
- On Windows, confirm WSL 2 integration is enabled if Docker prompts for it.

### Backend cannot reach Supabase

- `SUPABASE_URL` must match **`supabase status`** (scheme + host + port).
- Use the **anon** key for `SUPABASE_KEY` and **service_role** for `SUPABASE_SERVICE_ROLE_KEY`.

### Frontend shows auth or CORS errors

- Restart Vite after editing `mobile/.env`.
- Backend CORS is configured in [`backend/app/main.py`](../backend/app/main.py); for unusual dev hosts, you may need to add your origin.

### “Athlete profile not found”

- The JWT is valid but **`athletes.user_id`** does not match **`auth.users.id`**. Fix seed data or create the athlete row for your user (Studio **Table Editor** or seed SQL).

### Wrong Python version

- Install **Python 3.12** and recreate the venv: delete `backend/.venv`, then repeat section 5.

---

## 10. Where to read next

| Document | Topic |
|----------|--------|
| [SETUP.md](./SETUP.md) | Shorter setup, Garmin notes, webhook tunnels |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System design |
| [API_REFERENCE.md](./API_REFERENCE.md) | HTTP API |
| [MOBILE.md](./MOBILE.md) | Svelte 5, Capacitor, HealthKit |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Cloud Run, secrets, CI |
| [STRAVA_INTEGRATION.md](./STRAVA_INTEGRATION.md) | Strava OAuth and webhooks |

---

## 11. Command cheat sheet (copy-paste)

From **repo root** after Docker is up:

```bash
npm install
npx supabase start
npx supabase db push
npx supabase db reset
```

**Backend** (new terminal, from `backend/`):

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (new terminal, from `mobile/`):

```bash
npm install
npm run dev
```

Remember: **`backend/.env`** and **`mobile/.env`** must be created from the `.env.example` files and filled using **`npx supabase status`**.
