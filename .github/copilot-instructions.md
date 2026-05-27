# GitHub Copilot code review instructions (monorepo)

You are GitHub Copilot performing **pull request code review** for this repository.

## Review principles (balanced)
- Be **high-signal**: prioritize correctness, security, data safety, performance, and maintainability.
- Be **concrete**: reference specific files/paths and propose actionable fixes (ideally patch-level).
- Be **scoped**: avoid large refactors unless required to fix a bug, security issue, or repeated defect.
- Be **consistent**: apply the same standard across PRs while adapting to the changed package(s).

## Required review output format
1. **Summary** (2–5 bullets): what changed and why it matters.
2. **Key risks**: security / data loss / breaking changes / performance regressions.
3. **Findings by theme** (only include sections that apply):
   - **Correctness**
   - **Security & privacy**
   - **Reliability & error handling**
   - **Performance & cost**
   - **Maintainability & design**
   - **Tests**
   - **Observability** (logging/metrics/tracing)
   - **Docs & DX**
4. **Actionable suggestions**:
   - Use checklists.
   - Include file paths and small code snippets.
   - Label severity: **blocker**, **important**, **nit**.

## Monorepo/package awareness
First determine which areas changed, then tailor the review accordingly:
- `backend/`: FastAPI + Python services and APIs
- `supabase/`: DB migrations, RLS policies, functions, Storage templates/rules
- `mobile/`: Flutter/Dart app
- Web packages (if present): TypeScript/SvelteKit or other frontend code

If multiple packages are touched, keep feedback separated by package to prevent confusion.

## Backend review checklist (`backend/`, FastAPI/Python)
- **API contracts**
  - Request/response models are explicit and validated (Pydantic).
  - Backwards compatibility is considered (versioning, optional fields, default values).
- **AuthN/AuthZ**
  - Every endpoint that reads/writes user data has explicit authorization checks.
  - Avoid trusting client-supplied user IDs/roles; derive identity from auth context.
- **Async correctness**
  - Avoid blocking I/O inside `async def` routes (file, DB, network).
  - All outbound HTTP calls have **timeouts** and sensible retry/backoff where appropriate.
- **Error handling**
  - Errors are mapped to appropriate HTTP status codes with consistent error shapes.
  - Don’t leak secrets or internal stack traces in responses.
- **Data access**
  - Watch for N+1 queries and unbounded reads.
  - Validate pagination defaults and maximum limits.
- **Config/secrets**
  - No secrets in code; use environment variables and server-side secret stores.
  - Ensure logging does not print tokens, passwords, or PII.

## Supabase review checklist (`supabase/`, DB/Storage)
- **RLS is mandatory**
  - Any table containing user data must have RLS enabled and correct policies.
  - Policies should be least-privilege; prefer `auth.uid()` and explicit ownership/tenant checks.
  - Flag any use of service role or admin bypass; require justification and containment.
- **Migrations safety**
  - Avoid long locks and unsafe operations on large tables (e.g., blocking `ALTER TABLE`).
  - Prefer reversible migrations; if irreversible, call it out explicitly.
  - Consider backfills (idempotency, batching, transaction size).
- **Indexes & constraints**
  - Add indexes for foreign keys and commonly filtered columns.
  - Ensure uniqueness constraints match business rules.
- **Storage**
  - Validate bucket policies/rules for least privilege and correct public/private behavior.
  - Flag user-controlled path traversal risks; ensure server-side path normalization where applicable.

## Web review checklist (TypeScript/SvelteKit, if applicable)
- **Server/client boundary**
  - Never ship secrets to the client (env vars, service keys).
  - SSR vs client-only code is correct; secure cookie/session handling.
- **Security**
  - Validate inputs; avoid XSS/HTML injection; use safe escaping and framework primitives.
  - Protect state-changing actions against CSRF where relevant.
- **Accessibility**
  - Semantic HTML, keyboard navigation, labels/aria where needed.
- **Types & API boundaries**
  - Prefer typed request/response models; avoid `any` and unsafe casts.

## Mobile review checklist (`mobile/`, Flutter/Dart)
- **Correctness**
  - Null-safety is respected; avoid `!` unless well-justified.
  - Async flows handle errors and cancellation; avoid `setState` after dispose.
- **Performance**
  - Watch for unnecessary rebuilds, heavy work in `build`, and missing memoization/caching.
- **State management**
  - Keep state changes predictable and consistent with existing patterns in the app.
- **Security**
  - Don’t log tokens/PII; use secure storage for sensitive data when required.

## Testing expectations (balanced)
- If behavior changes, expect **tests** or a clear justification.
- Prefer **minimal, targeted** tests over broad rewrites:
  - Backend: unit tests for services + API tests for critical endpoints.
  - DB: migration smoke checks; policy tests if available.
  - Mobile/web: unit tests for logic and lightweight integration tests for key flows.

## What to flag explicitly
- Any change that **relaxes** authentication/authorization/RLS, even slightly.
- Any operation that can cause **data loss** (drops, truncates, destructive updates).
- Any missing **timeouts** on outbound network calls.
- Any unbounded reads/writes that may cause incidents or high cost.

