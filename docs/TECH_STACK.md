# Tech Stack

## Summary

ASTRAPHE is a SvelteKit/Svelte 5 frontend, FastAPI Python backend, Supabase data/auth/storage layer, Redis layer for caches, rate limits, and cross-replica coordination, and a Google GenAI-powered coaching system.

## Frontend

The frontend lives in `mobile/` and is a static SvelteKit SPA/PWA with Capacitor iOS support.

Key package versions from `mobile/package.json`:

| Package | Version | Purpose |
|---|---:|---|
| `svelte` | `5.55.5` | UI framework |
| `@sveltejs/kit` | `2.58.0` | Routing/app framework |
| `@sveltejs/adapter-static` | `3.0.10` | Static SPA build |
| `vite` | `8.0.10` | Dev/build tool |
| `typescript` | `6.0.3` | Type checking |
| `tailwindcss` | `3.4.19` | Styling |
| `@capacitor/core` | `8.3.1` | Native bridge |
| `@capacitor/ios` | `8.3.1` | iOS target |
| `@capacitor/push-notifications` | `8.1.0` | Native push |
| `@interval-health/capacitor-health` | `2.0.0` | HealthKit scaffold |
| `@supabase/supabase-js` | `2.105.0` | Auth/client SDK |
| `layerchart` | `1.0.13` | Svelte chart primitives |
| `d3` | `7.9.0` | Scales and visualization utilities |
| `maplibre-gl` | `5.24.0` | Map rendering |
| `marked` / `katex` / `dompurify` | `16.4.2` / `0.16.45` / `3.4.1` | Coach message rendering |
| `vite-plugin-pwa` | `^1.3.0` | PWA/service worker |
| `workbox-*` | `^7.4.1` | PWA caching/routing |
| `vitest` | `3.2.4` | Tests |

The frontend package requires Node 20+ and pnpm 10+ (CI pins pnpm `10.32.1` on Node 24). Android is not currently scaffolded.

## Backend

The backend lives in `backend/` (Docker image based on `python:3.12-slim`). Dependencies are in `backend/requirements.txt` with minimum-version pins.

Key choices:

| Technology | Purpose |
|---|---|
| Python 3.12 | Runtime |
| FastAPI / uvicorn | HTTP API |
| Pydantic v2 / pydantic-settings | Validation and config |
| NumPy / pandas | TSS, CTL, ATL, TSB, recovery, strain calculations |
| Supabase Python client (`supabase`) | PostgREST/Auth/Storage access |
| httpx | Third-party HTTP calls; one shared pool under every per-user Supabase client |
| PyJWT[crypto] | Local verification of Supabase user JWTs |
| google-genai | Coach, analysis, embeddings, grounding |
| openai | Optional OpenAI-compatible LLM provider |
| redis[hiredis] | Redis client (asyncio and sync) |
| garminconnect / fitdecode | Garmin Connect client and FIT parsing |
| cryptography | Fernet encryption of OAuth tokens at rest |
| pypdf / python-docx / openpyxl / xlrd | Coach document uploads |
| pywebpush | Web push notifications |
| firebase-admin | Native push notifications |
| pytest / pytest-cov | Backend tests (80% coverage gate in CI) |

The API holds no per-request state; shared state lives in Supabase and Redis, and production runs two replicas.

## AI

Defaults from `backend/app/config.py`:

| Setting | Default | Role |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Coach chat |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.1-flash-lite` | Chat fallback when the primary is overloaded or times out |
| `GEMINI_ANALYSIS_MODEL` | `gemini-3.1-flash-lite` | Screen insights, memory extraction |
| `GEMINI_IMPORT_MODELS` | `gemini-3-flash-preview,gemini-3.8-flash,gemini-3.6-flash` | Coach plan import, tried in order |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | Coach memory embeddings |
| `GEMINI_FREE_TIER` | `true` | Shared per-model RPM guardrail (`services/gemini_quota.py`) |

`LLM_PROVIDER=openai` plus `OPENAI_API_BASE_URL` routes chat/insights/memory extraction to any OpenAI-compatible server; `CHAT_LLM_PROVIDER`/`CHAT_MODEL` route only the coach chat there. Embeddings always use Gemini.

The coach uses:

- prompt file: `backend/app/prompts/coach_behavior.md`
- Google GenAI SDK: `from google import genai`
- custom function tools in `backend/app/services/coach_tools.py`
- Google Search grounding, or a SearXNG-backed `web_search` tool when `SEARXNG_URL` is set
- pgvector memories in `coach_memories`
- cached screen analysis in `athlete_analyses`

## Data Layer

Supabase provides:

- PostgreSQL
- Auth (including OAuth 2.1 server mode for the MCP server)
- Row Level Security
- Storage
- pgvector
- local development stack through Supabase CLI/Docker

The authoritative schema history is `supabase/migrations/`. See [DATA_MODELS.md](./DATA_MODELS.md) for the tables.

## MCP Server

`mcp-server/` is a standalone service that exposes read-only Astraphe data to any
MCP-compatible AI client (Claude Desktop, claude.ai Connectors, Claude Code) via the
official `mcp` Python SDK (`mcp[cli]>=2.0.0`), Streamable HTTP transport, and
OAuth 2.1 (RFC 8414/9728/7591/8707). Supabase Auth's OAuth Server mode acts as the
authorization server — see [MCP_SERVER.md](./MCP_SERVER.md) for the full architecture,
auth flow, and tool reference. It imports `backend/app`'s tool-handler functions directly
rather than duplicating them.

## Redis

Redis is optional locally (`docker compose up -d redis` runs `redis:7-alpine`) and expected in production.

It backs:

- global per-IP rate limiting
- per-athlete AI and expensive-action rate limiting
- athlete state/profile/zones, activity stream/detail, and Body screen caches (`core/body_cache.py`)
- cross-replica state: Gemini quota, plan-import daily count, analysis regeneration lock, coach reply progress, Garmin MFA logins, OAuth state nonces

If Redis is unavailable, rate limits and shared state fall back to process-local memory and caches are skipped. See [REDIS.md](./REDIS.md).

## Integrations

| Integration | Current Role |
|---|---|
| Supabase Auth | User identity and JWTs. |
| Supabase Storage | Coach uploads (`coach-uploads`) and gzip activity streams (`activity-streams`). |
| Strava | OAuth, webhooks, backfill, activity detail, streams, laps. |
| WHOOP | OAuth, webhooks, recovery/sleep/strain backfill. |
| Garmin | Username/password login via `garminconnect` (MFA supported), background poll loop: activities, biometrics, all-day heart rate, weigh-ins. |
| Intervals.icu | API-key connect, workouts, streams, wellness backfill. |
| Resend | Marketing privacy opt-in sync. |
| Firebase/FCM | Native push notification transport. |
| Web Push/VAPID | PWA push notification transport. |
| Photon | iMessage coach channel via the `photon-bridge/` Node service. |
| SearXNG | Optional coach web search. |
| Cloudflare Tunnel | Deploy-time SSH path to the k3s cluster. |
| Firebase Hosting | Static frontend hosting. |
| GHCR | Container registry for the API, MCP server, and photon-bridge. |

## Deployment

Current repo automation:

- Backend: `.github/workflows/deploy.yml` tests, builds `ghcr.io/sbalbale/astraphe-api` (tagged with the commit SHA), runs migrations, and rolls it out to the k3s cluster with `kubectl set image` (see [DEPLOYMENT.md](./DEPLOYMENT.md)).
- MCP server: the same workflow's `mcp-server`/`build-mcp`/`deploy-mcp` jobs test, publish, and roll out `ghcr.io/sbalbale/astraphe-mcp` — see [MCP_SERVER.md](./MCP_SERVER.md).
- Photon bridge: `photon-bridge`/`build-photon-bridge`/`deploy-photon-bridge` jobs do the same for `ghcr.io/sbalbale/astraphe-photon-bridge`.
- Frontend: Firebase Hosting workflows build `mobile/` with pnpm and deploy live/preview channels.

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

MCP server:

```bash
cd mcp-server
pip install -r ../backend/requirements.txt -r requirements.txt
python -m pytest
uvicorn astraphe_mcp.asgi:app --reload --port 8090
```
