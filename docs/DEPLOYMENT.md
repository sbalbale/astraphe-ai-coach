# Deployment

## Current Deployment Model

Current repo automation deploys:

- Backend API: GitHub Actions -> GHCR container image -> Proxmox Docker host over Cloudflare Access SSH.
- Frontend: GitHub Actions -> Firebase Hosting.
- Database migrations: GitHub Actions SSH step runs migration SQL against the remote Supabase/Postgres container.

`backend/cloudbuild.yaml` remains in the repo as an alternate/historical Cloud Run pipeline. It is not the current primary deployment path in `.github/workflows/`.

## Backend Workflow

Source:

```text
.github/workflows/deploy.yml
```

Trigger:

- Push to `main`
- Changes under `backend/**` or `.github/workflows/deploy.yml`

Jobs:

1. `build`
   - Checks out the repo.
   - Logs in to GitHub Container Registry.
   - Builds `./backend`.
   - Pushes:
     - `ghcr.io/sbalbale/astrape-api:latest`
     - `ghcr.io/sbalbale/astrape-api:${{ github.sha }}`

2. `deploy`
   - Installs `cloudflared`.
   - Configures SSH through Cloudflare Access.
   - Copies Supabase email templates to the host.
   - Runs:

```bash
cd ~/astrape
docker compose pull astrape-api
docker compose up -d astrape-api
docker image prune -f
docker compose ps
```

3. `migrate`
   - Reuses the Cloudflare SSH path.
   - Applies SQL files from `~/astrape/repo/supabase/migrations/*.sql` into the `supabase-db` container with `psql`.

## Backend Required Secrets

GitHub Actions deployment secrets:

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` | GHCR push via GitHub Actions. |
| `CF_ACCESS_CLIENT_ID` | Cloudflare Access service token ID. |
| `CF_ACCESS_CLIENT_SECRET` | Cloudflare Access service token secret. |
| `PROXMOX_SSH_KEY` | SSH private key for `docker@ssh.astrapeai.com`. |

Runtime secrets are provided by the deployed Docker environment, not directly by the workflow file. Keep these aligned with `backend/.env.example`:

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
| `FIREBASE_SERVICE_ACCOUNT_ASTRAPE_AI_COACH` | Firebase hosting deploy auth. |
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

The current backend deploy workflow applies migration files by piping each file into the remote `supabase-db` container. Be careful with non-idempotent SQL: migration files should be safe for the deployment mechanism being used.

For local development:

```bash
npx supabase db push
```

For production, use the workflow or the operational process for the deployed Supabase/Postgres instance.

## Health And Verification

After backend deployment:

```bash
curl https://api.astrapeai.com/health
```

Expected shape:

```json
{
  "status": "healthy",
  "service": "ASTRAPE API",
  "version": "1.0.0",
  "redis": "connected",
  "supabase": "connected"
}
```

Verify:

- Backend container is running on the Proxmox host.
- `/health` is reachable through the public API host.
- Supabase reports expected migration state.
- Redis is connected when `REDIS_URL` is configured.
- Firebase Hosting serves the latest build.
- Frontend `VITE_API_URL` points at the current public API host.

## Production Backend Behavior

When `APP_ENV=production`:

- FastAPI docs and Redoc are disabled.
- Debug router is not registered.
- Startup rejects `TEST_ATHLETE_ID`.
- Security headers are added to responses.
- CORS uses the configured allowlist in `backend/app/main.py`.

## Cloud Run Notes

`backend/cloudbuild.yaml` documents a Cloud Build/Cloud Run path. Treat it as an alternate or historical deployment path unless the active workflow is changed back to Cloud Run. If Cloud Run is reactivated, update this document and `docs/TECH_STACK.md` with the exact project, region, secrets, and access policy.
