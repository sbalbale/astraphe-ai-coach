# Deployment

This doc has two parts: **how the maintainer's reference instance is deployed** (private infra you can't replicate, described here for transparency/context only), and **how to self-host** (what you'd actually do to run your own instance).

## How the reference instance is deployed

This section describes `sbalbale/astraphe-ai-coach`'s own production deployment — not something a contributor needs to set up, and not required to run this project yourself. Skip to [Self-Hosting](#self-hosting) below if that's what you're after.

- Backend API: GitHub Actions -> GHCR container image -> `kubectl set image` against a private k3s cluster, reached over a Cloudflare Access SSH tunnel.
- MCP server: same GHCR/k3s pattern, separate image (`ghcr.io/sbalbale/astraphe-mcp`) and separate `astraphe-mcp` Deployment/Service — see [MCP_SERVER.md](./MCP_SERVER.md).
- Frontend: GitHub Actions -> Firebase Hosting, via a custom REST-API deploy script (`mobile/scripts/deploy-firebase-hosting-rest.mjs`).
- Database migrations: GitHub Actions SSHes in and runs `supabase db push` against the cluster's Postgres pod via `kubectl port-forward`.

This is entirely specific to the maintainer's private infrastructure (hostnames, k8s namespaces, service accounts) and isn't usable by anyone else — see `.github/workflows/deploy.yml` if you're curious about the mechanics, but there's nothing to reuse there for your own deployment.

## Self-Hosting

To run your own instance, you need: a Postgres 17 database (self-hosted Supabase via `supabase start`/`supabase db push`, or hosted Supabase), the backend container (`backend/Dockerfile`) running anywhere that can reach it (Docker Compose, a VM, any container platform, Cloud Run, Fly.io, etc.), and the mobile app built and served as a static SvelteKit site (`pnpm build` in `mobile/`) — Firebase Hosting, Vercel, Netlify, Cloudflare Pages, or any static host all work.

The backend is a stateless FastAPI service reading config entirely from environment variables (`backend/.env.example`) — no code changes needed to point it at your own Supabase project, Gemini API key, and OAuth app credentials for Strava/WHOOP/Garmin. See [SETUP.md](./SETUP.md) for the full local dev walkthrough as a starting point; adapt the same env vars to whatever hosting platform you use in production.

## Contributor CI

`.github/workflows/deploy.yml` also runs on every pull request (`backend` and `mobile` jobs run pytest / vitest+svelte-check, and `build` compiles the Docker image without pushing it) — so PRs get build+test coverage automatically, without needing any of the deploy secrets below. Only the `deploy` and `migrate` jobs (gated to `push` events on `main`) touch the maintainer's private infrastructure.

## Reference: the maintainer's production deploy in detail

## Backend Workflow

Source:

```text
.github/workflows/deploy.yml
```

Trigger:

- `backend`/`mobile`/`build` jobs: every push and every pull request to `main`.
- `deploy`/`migrate` jobs: only on push to `main` (never on pull requests, and never for fork PRs).

Jobs:

1. `backend` — runs `pytest` with an 80% coverage gate. No secrets needed (`config.py` defaults to test placeholders, external calls are mocked).
2. `mobile` — runs `pnpm test:coverage` (vitest, 80%/75% branch gate).
3. `build` — builds the backend Docker image; only pushes to GHCR (`ghcr.io/sbalbale/astraphe-api`) on an actual push to `main`, never on a PR.
4. `deploy` (push-to-main only) — SSHes into the k3s cluster via a Cloudflare Access tunnel and runs `kubectl set image deployment/astraphe-api` against a narrowly-scoped `ci-deployer` ServiceAccount, then waits for rollout.
5. `migrate` (push-to-main only) — port-forwards to the cluster's `supabase-db-0` Postgres pod and runs `supabase db push`.

## Backend Required Secrets

GitHub Actions deployment secrets:

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` | GHCR push via GitHub Actions. |
| `CF_ACCESS_CLIENT_ID` | Cloudflare Access service token ID. |
| `CF_ACCESS_CLIENT_SECRET` | Cloudflare Access service token secret. |
| `PROXMOX_SSH_KEY` | SSH private key authorized as root on the k3s cluster nodes (name is historical — the target moved from a Proxmox Docker host to k3s). |
| `SUPABASE_DB_PASSWORD` | Postgres password for `supabase db push` (migrate job), matching the cluster's Postgres pod. |

Runtime secrets are provided by the deployed environment, not directly by the workflow file. Keep these aligned with `backend/.env.example`:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_ANALYSIS_MODEL`
- `GEMINI_EMBEDDING_MODEL`
- `REDIS_URL`
- WHOOP/Garmin/Strava credentials
- Resend credentials
- Push credentials

## Frontend Workflow

Live deploy:

```text
.github/workflows/firebase-hosting-merge.yml
```

Preview deploy:

```text
.github/workflows/firebase-hosting-pull-request.yml
```

Both workflows:

- Use pnpm.
- Run `pnpm install && pnpm build` in `mobile/`.
- Pass Vite env vars from GitHub secrets.
- Deploy with `FirebaseExtended/action-hosting-deploy@v0`.

Frontend secrets:

| Secret | Purpose |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_ASTRAPHE_AI_COACH` | Firebase hosting deploy auth. |
| `VITE_API_URL` | Public API base URL. |
| `VITE_SUPABASE_URL` | Supabase project URL. |
| `VITE_SUPABASE_KEY` | Supabase anon key. |
| `VITE_VAPID_PUBLIC_KEY` | Web push public key. |

Hosting config:

```text
mobile/firebase.json
```

It serves `mobile/build`, sets no-cache headers for service-worker/workbox assets, caches immutable SvelteKit build assets, and rewrites all paths to `/index.html`.

## Database Deployment

Migrations live in:

```text
supabase/migrations/
```

The current backend deploy workflow port-forwards to the cluster's Postgres pod and runs `supabase db push`. Migration files should be idempotent/safe to re-run, since `db push` applies whatever hasn't been applied yet.

For local development:

```bash
npx supabase db push
```

For production, use the workflow or the operational process for the deployed Supabase/Postgres instance.

## Auth Email Templates (Manual k3s Step — Not Automated)

`supabase/templates/*.html` (confirmation, recovery, invite) are **not** wired into the production k3s `auth` (GoTrue) Deployment. CI only patches the `astraphe-api`/`astraphe-mcp` image tags and runs `supabase db push` for migrations — it never touches the auth pod's mailer config (see the note in `.github/workflows/deploy.yml` near the deploy steps). `supabase db push` / `supabase link` only push config for a Supabase Cloud-linked project; they have no effect on a self-hosted GoTrue pod's env vars.

As a result, production currently sends GoTrue's generic default emails regardless of what's in `supabase/templates/`, until someone manually updates the live `auth` Deployment/Secret (outside this repo, since no `k8s/`/`infra/`/`deploy/` manifests are checked in here) to either:

- Set `GOTRUE_MAILER_TEMPLATES_CONFIRMATION` / `GOTRUE_MAILER_TEMPLATES_RECOVERY` / `GOTRUE_MAILER_TEMPLATES_INVITE` to publicly reachable URLs serving these template files, or
- Mount them into the pod via a ConfigMap + volume mount and point the equivalent `*_content_path`-style config at them.

Until that manual change is made, the styled templates (including the emailed 6-digit verification code in `confirm.html`) only render when testing locally via `npx supabase start` (which does read `supabase/config.toml`'s `[auth.email.template.*]` blocks) — not in production.

## Health And Verification

After backend deployment:

```bash
curl https://api.astrapheai.com/health
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

Verify:

- The backend pod/container is running and healthy.
- `/health` is reachable through the public API host.
- Supabase reports expected migration state.
- Redis is connected when `REDIS_URL` is configured.
- Firebase Hosting (or whatever you use) serves the latest build.
- Frontend `VITE_API_URL` points at the current public API host.

## Production Backend Behavior

When `APP_ENV=production`:

- FastAPI docs and Redoc are disabled.
- Debug router is not registered.
- Startup rejects `TEST_ATHLETE_ID`.
- Security headers are added to responses.
- CORS uses the configured allowlist in `backend/app/main.py`.
