# Contributing to ASTRAPHE

Thank you for your interest in contributing! This guide covers what you need to get started.

## Development Setup

See [docs/SETUP.md](./docs/SETUP.md) for the complete local development setup guide. The TL;DR:

```bash
# 1. Prerequisites: Docker, Node.js 20+, Python 3.12, pnpm 10+
# 2. Install the Supabase CLI and start the local stack (applies migrations)
npm install
npx supabase start

# 3. Start Redis (optional)
docker compose up -d redis

# 4. Configure backend
cp backend/.env.example backend/.env
# Edit backend/.env: APP_ENV=development, plus Supabase keys from `npx supabase status`

# 5. Start backend
cd backend
python -m venv .venv
source .venv/bin/activate   # On Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 6. Configure and start the frontend
cd ../mobile
cp .env.example .env
pnpm install
pnpm run dev
```

## Workflow

1. **Fork** the repository and create a branch from `main`.
2. **Branch naming:** `feat/<description>`, `fix/<description>`, `docs/<description>`.
3. **Commit messages:** use [Conventional Commits](https://www.conventionalcommits.org/), with a scope where it helps (e.g. `fix(heart-rate): ...`):
   - `feat:` new feature
   - `fix:` bug fix
   - `perf:` performance improvement
   - `style:` visual/UI styling changes
   - `docs:` documentation changes
   - `refactor:` code restructuring (no behavior change)
   - `test:` adding or updating tests
   - `chore:` maintenance (deps, config, tooling)
4. **Push and open a Pull Request** against `main`.

## Code Style

There is no linter or formatter configuration checked in for either the backend or the frontend; match the style of the code around your change.

### Python (Backend)

- **Tests:** new features should include tests. Run from the repo root:
  ```bash
  python -m pytest
  python -m pytest --cov=app   # CI enforces 80% coverage
  ```
- **Docstrings:** public functions should have a docstring describing what they do.

### TypeScript / Svelte (Mobile)

- **Type checking:** run `pnpm run check` before committing (CI does not run it).
- **Testing:** unit tests with Vitest: `pnpm run test`, or `pnpm run test:coverage` for the CI thresholds (80% lines, 75% branches).
- **Components:** one component per file. Use Svelte 5 runes (`$state`, `$derived`) for reactive state.

## Testing

- **Backend:** `python -m pytest` from the repo root. The suite ignores `backend/.env` and mocks external services, so no keys are needed.
- **MCP server:** `python -m pytest` in `mcp-server/` (CI enforces 80% coverage).
- **Mobile:** `cd mobile && pnpm run test`.
- **Photon bridge:** `cd photon-bridge && npm test`.

Every pull request runs these suites and builds the Docker images in CI; see [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md#contributor-ci).

## Architecture Overview

- `backend/` — FastAPI service (Python 3.12, Pydantic v2)
- `mobile/` — Svelte 5 + SvelteKit app, served as a static PWA and wrapped for iOS with Capacitor (TypeScript, Tailwind)
- `mcp-server/` — MCP server exposing athlete data to MCP clients
- `photon-bridge/` — Node bridge for the iMessage coach channel
- `supabase/` — database migrations, RLS policies, auth email templates, seed data
- `docs/` — architecture, API reference, deployment, and setup docs

## Pull Requests

- Ensure all tests pass.
- Migrations must be backward-compatible with the previous release (additive changes), because production applies them before deploying the new API. See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md).
- Update documentation if behavior changes.
- Describe the what and why in the PR description.
- Reference any related issues.

## Getting Help

- Check [docs/SETUP.md](./docs/SETUP.md#common-problems) for common setup problems.
- Check existing issues before opening a new one.
- Feel free to ask questions in PR discussions.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.
