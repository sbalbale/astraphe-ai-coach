# Deployment

This doc has three parts: **CI** (what runs on pull requests), **how the maintainer's reference instance is deployed** (private infrastructure, described for context only), and **how to self-host**.

## Contributor CI

`.github/workflows/deploy.yml` runs on every pull request into `main` (no `paths` filter, because its jobs are required status checks) and on pushes to `main` that touch `backend/`, `mobile/`, `supabase/`, `mcp-server/`, `photon-bridge/`, or the workflow itself.

On a pull request these jobs run, and none of them needs deploy secrets:

| Job | What it does |
|---|---|
| `backend` | `python -m pytest --cov=app` from the repo root with the 80% coverage gate in `.coveragerc`. `config.py` defaults to test placeholders and external calls are mocked. |
| `mcp-server` | pytest for `mcp-server/` with an 80% coverage gate. |
| `mobile` | `pnpm test:coverage` in `mobile/` (Vitest, 80% lines / 75% branches). It does not run `svelte-check`; run `pnpm run check` yourself. |
| `photon-bridge` | `npm ci && npm test` in `photon-bridge/`. |
| `build`, `build-mcp`, `build-photon-bridge` | Build the Docker images without pushing them. |

`.github/workflows/firebase-hosting-pull-request.yml` also builds the frontend and deploys a Firebase Hosting preview channel (`pr-<number>`, 7-day expiry) for PRs from branches in this repo (not forks), then comments the preview URL on the PR.

## How the reference instance is deployed

This section describes `sbalbale/astraphe-ai-coach`'s own production deployment. It is specific to the maintainer's infrastructure (hostnames, namespaces, service accounts) and is not needed to run the project yourself; skip to [Self-Hosting](#self-hosting) for that.

- **API:** `astraphe-api` runs in a k3s cluster (namespace `astraphe`) as **two replicas** sharing a **Redis** instance. Redis carries state the replicas must share: rate limits, caches, Gemini quota counters, plan-import quotas, and in-progress Garmin MFA logins.
- **MCP server:** a separate `astraphe-mcp` Deployment in the same namespace, from its own image (`ghcr.io/sbalbale/astraphe-mcp`). See [MCP_SERVER.md](./MCP_SERVER.md).
- **Photon bridge:** a single-replica `photon-bridge` Deployment (bootstrapped once from `photon-bridge/k8s.yaml`). See [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md).
- **Database:** self-hosted Supabase in the same cluster (namespace `supabase`, Postgres pod `supabase-db-0`).
- **Frontend:** the static SvelteKit build on Firebase Hosting (project and site `astrapheai`).

### Deploy jobs (push to `main` only)

The jobs below run only on a push to `main` (after a merge), never on pull requests. Each reaches the cluster by SSH through a Cloudflare Access tunnel (`ssh.astrapheai.com`, pinned host keys in `.github/ssh_known_hosts`) and runs `kubectl` with a narrowly scoped `ci-deployer` kubeconfig that can only patch images and read rollout status.

| Job | Needs | What it does |
|---|---|---|
| `build` / `build-mcp` / `build-photon-bridge` | — | Push `:latest` and `:<commit sha>` tags to GHCR (`ghcr.io/sbalbale/astraphe-api`, `astraphe-mcp`, `astraphe-photon-bridge`). |
| `migrate` | `build`, `backend`, `mobile` | Copies `supabase/migrations`, `supabase/templates` and `supabase/config.toml` to a cluster node, port-forwards to `supabase-db-0`, and runs `supabase db push` (pinned Supabase CLI). |
| `deploy` | `build`, `backend`, `mobile`, `migrate` | `kubectl set image deployment/astraphe-api` to the commit-SHA image, then waits for the rollout. |
| `deploy-mcp` | `build-mcp`, `mcp-server` | Same for `deployment/astraphe-mcp`. |
| `deploy-photon-bridge` | `build-photon-bridge`, `photon-bridge` | Same for `deployment/photon-bridge`. |

Because `migrate` runs before `deploy` and a failed migration skips the deploy, new code never goes live against a schema that lacks its columns. The flip side: migrations must stay backward-compatible with the previous release (additive changes such as `ADD COLUMN IF NOT EXISTS`, not a `DROP`/`RENAME` in the same change as the code that stops using it).

`.github/workflows/firebase-hosting-merge.yml` builds `mobile/` and deploys it to the live Firebase Hosting site on every push to `main`.

`.github/workflows/release.yml` creates a GitHub release when a `v*` tag is pushed (or from a manual run with a tag name). It uses `docs/releases/<tag>.md` as the notes when that file exists, otherwise GitHub's generated notes, and marks tag-push releases as pre-releases.

### GitHub Actions secrets

| Secret | Used by | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | build jobs, release | GHCR push; creating releases. |
| `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` | deploy jobs, migrate | Cloudflare Access service token for the SSH tunnel. |
| `PROXMOX_SSH_KEY` | deploy jobs, migrate | SSH key for the k3s nodes (the name is historical: the target used to be a Proxmox Docker host). |
| `SUPABASE_DB_PASSWORD` | migrate | Postgres password for `supabase db push`. |
| `FIREBASE_SERVICE_ACCOUNT_ASTRAPHEAI` | Firebase workflows | Firebase Hosting deploy auth. |
| `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_KEY`, `VITE_VAPID_PUBLIC_KEY` | Firebase workflows | Build-time frontend config. |

Runtime settings for the API (Supabase URL and keys, `GEMINI_API_KEY`, `REDIS_URL`, `OAUTH_TOKEN_ENCRYPTION_KEY`, provider credentials, push and email keys) are set on the cluster Deployments, not in the workflows. See `backend/app/config.py` for the full list.

### Frontend hosting

Both Firebase workflows run `pnpm install && pnpm build` in `mobile/` with the Vite variables above, then deploy with `mobile/scripts/deploy-firebase-hosting-rest.mjs`, a small script that calls the Firebase Hosting REST API (no Firebase CLI or third-party action).

`mobile/firebase.json` serves `mobile/build`, sets no-cache headers for the service worker and Workbox files, caches immutable SvelteKit build assets, and rewrites all paths to `/index.html`.

### Auth email templates (manual step, not automated)

`supabase/templates/*.html` (confirmation, recovery, invite) are **not** wired into the production `auth` (GoTrue) Deployment. CI copies the templates to the node alongside the migrations, but `supabase db push` only applies migrations; it never changes the auth pod's mailer settings (see the note in `.github/workflows/deploy.yml`).

Production therefore sends GoTrue's default emails until someone updates the live `auth` Deployment (no manifests for it are in this repo) to either:

- set `GOTRUE_MAILER_TEMPLATES_CONFIRMATION` / `GOTRUE_MAILER_TEMPLATES_RECOVERY` / `GOTRUE_MAILER_TEMPLATES_INVITE` to public URLs serving these files, or
- mount them from a ConfigMap and point the mailer config at them.

Until then the styled templates (including the 6-digit code in `confirm.html`) only render locally under `npx supabase start`, which reads the `[auth.email.template.*]` blocks in `supabase/config.toml`.

## Self-Hosting

To run your own instance you need:

- **Postgres with Supabase** (Auth, Storage, PostgREST): self-hosted Supabase or a hosted Supabase project. Apply `supabase/migrations/` with `supabase db push`. Local dev uses Postgres 17 (`supabase/config.toml`).
- **The API** from `backend/Dockerfile`, on any container platform that can reach Supabase. It reads all config from environment variables (`backend/app/config.py`, `backend/.env.example`). Set `APP_ENV=production` and a Fernet `OAUTH_TOKEN_ENCRYPTION_KEY`, or the API will not start in production mode.
- **Redis** if you run more than one API replica. Without `REDIS_URL` the API falls back to in-process rate limits and caches, which is fine for a single instance only.
- **The frontend** built with `pnpm build` in `mobile/` and served from any static host (Firebase Hosting, Vercel, Netlify, Cloudflare Pages, and so on). Set the `VITE_*` variables at build time.

`backend/app/main.py` hard-codes the production CORS allowlist (`ALLOWED_ORIGINS`) and `backend/app/routers/sync.py` hard-codes the allowed OAuth return hosts. Add your own domains there.

See [SETUP.md](./SETUP.md) for the local setup; the same environment variables apply in production.

## Health and Verification

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

`status` is `degraded` when Supabase is unreachable, and `redis` is `unavailable` when Redis is not configured or down. `/health` is exempt from IP rate limiting.

## Production Backend Behavior

When `APP_ENV=production` (also the default when `APP_ENV` is unset):

- `/docs` and `/redoc` are disabled.
- The debug router is not registered.
- Startup fails if `TEST_ATHLETE_ID` is set.
- Startup fails without a valid `OAUTH_TOKEN_ENCRYPTION_KEY`.
- CORS allows only the fixed origins in `backend/app/main.py` (no localhost or LAN origins).

Security headers are added to every response in all environments.
