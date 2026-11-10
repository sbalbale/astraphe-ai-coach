# GitHub Copilot code review instructions (monorepo)

You are GitHub Copilot performing **pull request code review** for this repository.

## Review principles
- Be **high-signal**: prioritize correctness, security, data safety, performance, and maintainability.
- Be **concrete**: reference specific files/paths and propose actionable fixes (ideally patch-level).
- Be **scoped**: avoid large refactors unless required to fix a bug, security issue, or repeated defect.
- Be **consistent**: apply the same standard across PRs while adapting to the changed package(s).

## Required review output format
1. **Summary** (2–5 bullets): what changed and why it matters.
2. **Key risks**: security / data loss / breaking changes / performance regressions.
3. **Findings by theme** (only sections that apply): Correctness, Security & privacy,
   Reliability & error handling, Performance & cost, Maintainability & design, Tests,
   Observability, Docs & DX.
4. **Actionable suggestions**: checklists with file paths and small snippets, each labeled
   **blocker**, **important**, or **nit**.

## Monorepo areas
Determine which areas changed and keep feedback separated by area:
- `backend/`: FastAPI (Python 3.12) API. Conventions: `.cursor/rules/astraphe-backend.mdc`.
- `supabase/`: SQL migrations (`supabase/migrations/`), RLS policies, seeds, email templates.
- `mobile/`: SvelteKit + Svelte 5 + TypeScript + Tailwind 3 app, shipped as a PWA (Firebase
  Hosting) and iOS app (Capacitor). Conventions: `.cursor/rules/frontend-design.mdc`.
- `mcp-server/`: read-only MCP server (Python) that reuses `backend/app` code.
- `photon-bridge/`: Node bridge for the iMessage (Photon) coach channel.
- `.github/workflows/`: CI and deploy (`deploy.yml` tests, builds GHCR images, deploys to k3s).

## Backend checklist (`backend/`)
- **AuthN/AuthZ**
  - Identity comes from `Depends(get_current_athlete)` (athlete id); never trust a
    client-supplied athlete/user id.
  - User data is read with `get_user_db` (RLS applies). Flag new `get_admin_db`
    (service role, bypasses RLS) usage outside webhooks/background jobs/admin routes, and
    any admin query not filtered by `athlete_id`.
  - Tier/model/rate-limit values must come from `app_metadata`, never `user_metadata`.
  - Webhooks must verify the sender (signature or subscription id) before processing.
- **Async correctness**
  - Sync SDK calls (Supabase, google-genai, garminconnect) in `async def` code must go
    through `run_supabase_call` / `asyncio.to_thread`.
  - Outbound HTTP calls have timeouts; background work uses `services/background.spawn`.
- **Multi-replica safety** (production runs two API replicas)
  - Module-level dicts/sets holding state that must be shared (locks, quotas, one-time
    tokens, cross-request flows) are bugs: it belongs in Redis with a process-memory fallback.
  - Every new Redis cache key needs a TTL. Writes to athlete data must retire caches
    (`invalidate_athlete_caches`, or bump `body_version` via `core/body_cache.py`).
- **Data access**: watch for N+1 queries, unbounded reads, missing pagination limits.
- **AI output**: model-supplied tool arguments are validated before DB writes; only the
  `<response>` text reaches the athlete.
- **Errors & secrets**: `HTTPException` with sensible status codes; settings via
  `app.config.settings`; no tokens/PII in logs or responses.

## Supabase checklist (`supabase/`)
- **RLS is mandatory** on any table with user data; least-privilege policies keyed on
  `auth.uid()` ownership. Flag anything that relaxes a policy.
- **Migrations**: new timestamped file in `supabase/migrations/`; avoid long locks on large
  tables; call out irreversible changes; backfills are idempotent and batched.
- **Indexes & constraints**: index foreign keys and common filters; uniqueness matches business rules.
- **Storage**: buckets private unless intentionally public; guard against path traversal.

## Mobile checklist (`mobile/`)
- **Svelte 5**: runes (`$props`, `$state`, `$derived`, `$effect`), `onclick`-style events,
  snippets; no `export let`, `$:`, or new `writable` stores. Watch `$effect` loops and
  missing cleanup.
- **Design tokens**: Tailwind tokens from `tailwind.config.js` / `app.css`, no standard
  palette colors, opacity modifiers on the /5 scale, hex (not `var()`) in canvas/D3/MapLibre.
- **Security**: never ship secrets (only public `VITE_*` values); sanitize rendered
  Markdown/HTML (DOMPurify); don't log tokens/PII.
- **Logic**: the app displays server-computed training metrics; it does not compute
  TSS/CTL/ATL/TSB. API calls go through `$lib/api.ts`.
- **Accessibility**: semantic HTML, labels, keyboard focus.

## Testing expectations
- Behavior changes need tests or a clear justification; prefer minimal, targeted tests.
- Backend: `python -m pytest` from the repo root (80% coverage gate in CI). Tests must
  stay hermetic (no real Supabase, Redis, or provider calls).
- Mobile: `pnpm test` / `pnpm test:coverage` (Vitest; 80% lines, 75% branches over
  `src/lib`) and `pnpm check` (svelte-check), run in `mobile/`.
- MCP server: `python -m pytest` in `mcp-server/` (80% gate).

## Flag explicitly
- Any change that **relaxes** authentication, authorization, or RLS.
- Any operation that can cause **data loss** (drops, truncates, destructive updates).
- Missing **timeouts** on outbound network calls.
- Unbounded reads/writes that may cause incidents or high cost (including LLM calls
  outside the shared quota/rate limits).
