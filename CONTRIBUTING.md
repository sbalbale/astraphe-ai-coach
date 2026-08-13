# Contributing to ASTRAPHE

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

See [docs/SETUP.md](./docs/SETUP.md) for the complete local development setup guide. The TL;DR:

```bash
# 1. Prerequisites: Docker, Node.js 20+, Python 3.12, pnpm 10+
# 2. Start Supabase local stack
npx supabase start
npx supabase db push

# 3. Start Redis (optional but recommended)
docker compose up -d redis

# 4. Configure backend
cp backend/.env.example backend/.env
# Edit backend/.env with your Supabase keys (from supabase status)

# 5. Start backend
cd backend
python -m venv .venv
source .venv/bin/activate   # On Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 6. Configure and start mobile frontend
cd ../mobile
pnpm install
pnpm run dev
```

## Workflow

1. **Fork** the repository and create a branch from `main`.
2. **Branch naming:** `feature/<description>`, `fix/<description>`, `docs/<description>`.
3. **Commit messages:** Use [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation changes
   - `refactor:` code restructuring (no behavior change)
   - `test:` adding or updating tests
   - `chore:` maintenance (deps, config, tooling)
4. **Push and open a Pull Request** against `main`.

## Code Style

### Python (Backend)

- **Formatter:** We use `ruff`. Run before committing:
  ```bash
  cd backend
  ruff check .
  ruff format .
  ```
- **Type checking:** Run `mypy` on changed modules.
- **Tests:** All new features should include tests. Run:
  ```bash
  cd backend
  python -m pytest tests -v
  ```
- **Docstrings:** Every public function must have a docstring describing purpose, parameters, and return value.

### TypeScript / Svelte (Mobile)

- **Type checking:** Run `pnpm run check` before committing.
- **Testing:** Unit tests with Vitest. Run `pnpm run test`.
- **Linting:** Follow the Svelte/ESLint config in `mobile/`.
- **Components:** One component per file. Use Svelte 5 runes (`$state`, `$derived`) for reactive state.

## Testing

- **Backend:** Run `cd backend && python -m pytest tests -v`. New features require unit tests.
- **Mobile:** Run `cd mobile && pnpm run test`. Focus on utility functions and data transformations.

## Architecture Overview

- `backend/` — FastAPI service (Python 3.12, FastAPI, Pydantic v2)
- `mobile/` — Svelte 5 + SvelteKit PWA (TypeScript, Tailwind)
- `supabase/` — Database migrations, RLS policies, seed data
- `docs/` — Architecture, API reference, deployment, and setup docs

## Pull Requests

- Ensure all tests pass.
- Update documentation if behavior changes.
- Describe the what and why in the PR description.
- Reference any related issues.

## Getting Help

- Check [docs/SETUP.md](./docs/SETUP.md) for common setup issues.
- Check existing issues before opening a new one.
- Feel free to ask questions in PR discussions.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.
