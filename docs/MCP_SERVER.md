# MCP Server

Astraphe ships a standalone [MCP](https://modelcontextprotocol.io) (Model Context Protocol)
server that lets you connect your own Astraphe data — workouts, biometrics, training load,
coach memory — to any MCP-compatible AI client: Claude Desktop, claude.ai Connectors,
Claude Code, or anything else that speaks MCP over Streamable HTTP with OAuth.

It lives in `mcp-server/` as a separate service from the main API (`backend/`), with its
own Dockerfile, its own deployment, and its own auth story — see [Architecture](#architecture)
for why.

**Status: Phase 2 (read-only, self-registering clients).** The tools below let a connected
client read your data. Nothing it can call writes anything back to Astraphe yet. Dynamic
Client Registration is on in production, so any MCP client — not just manually-registered
test ones — can connect without a maintainer having to hand it a client ID first; that's
also why the per-athlete rate limit exists (see [Rate limiting](#rate-limiting)). See
[Rollout](#rollout) for what's coming.

## Connecting a client

1. Your Astraphe account already exists (mobile app sign-in). No separate setup needed
   on the Astraphe side — the connection is authorized per-client the first time you
   connect.
2. In your MCP client (e.g. Claude Desktop → Settings → Connectors → Add custom
   connector, or claude.ai → Connectors), add:
   ```
   https://mcp.astrapheai.com/mcp
   ```
3. The client opens a browser window to Astraphe's sign-in/consent screen
   (`/oauth/consent` in the mobile web app). Sign in if you aren't already, then approve
   the connection.
4. That's it — the client can now call the tools listed below, scoped to your account
   only.

To disconnect, revoke the connection from your MCP client's settings (or, if you were
testing locally, delete the OAuth client registration in Supabase).

## Tools (read-only)

| Tool | What it returns |
|---|---|
| `list_workouts` | Completed workouts (duration, HR, power, TSS, strain) filtered by date/sport |
| `get_workout_summary` | Coaching summary for one workout: HR zone split, TSS, strain |
| `get_workout_streams_window` | Downsampled HR/power/pace for a specific minute/interval of one workout |
| `list_planned_workouts` | Future planned workouts on the training calendar |
| `get_training_load_series` | Daily TSS/CTL/ATL/TSB history (default last 42 days) |
| `get_biometrics_for_dates` | Sleep, HRV, recovery, strain for up to 7 specific dates |
| `summarize_workouts` | Rollup of completed workouts for a week/month/range: total TSS, hours, sport mix |
| `compare_workouts` | Side-by-side comparison of two completed workouts |
| `get_athlete_zones` | HR zone boundaries and FTP/threshold anchors |
| `list_memories` | Coach memories (race goals, injuries, preferences, etc.) |
| `simulate_training_impact` | Projects CTL/ATL/TSB on a target date after an assumed TSS load — a read-only projection, writes nothing |
| `calculate_nutrition` | Estimates energy/carb/fluid targets for a planned effort — pure computation, writes nothing |

Each tool's input schema is inferred from its Python type hints in
`mcp-server/astraphe_mcp/tools/read_tools.py`; field names and semantics are transcribed
from the same tool definitions the in-app AI coach already uses
(`backend/app/services/coach_tools.py`), so behavior matches exactly.

## Architecture

### Why a separate service

The MCP server reuses `backend/app/services/coach_tools.py`'s handler functions directly
(the same functions the in-app coach's own agentic tool-calling already exercises) —
they're plain `(args, athlete_id, db) -> dict` functions with zero LLM-provider coupling,
so there's nothing to reimplement for the actual data access. What's genuinely new is
everything HTTP/auth/protocol-shaped: the MCP tool registrations, the OAuth resource-server
wiring, and the Streamable HTTP transport.

It's deployed as its own service rather than bolted onto the existing FastAPI app because:
mounting a Streamable HTTP MCP endpoint on an existing FastAPI app has known rough edges in
the current SDK, and every comparable production MCP server (Linear, Sentry, Notion,
Stripe) is architected the same way — a separate resource server, not a route on the main
API.

To make the reuse work without restructuring `backend/` into an installable library,
`mcp-server/astraphe_mcp` is deliberately named differently from `backend/app` (so they can
coexist on `PYTHONPATH` without collision) and imports straight from `app.services.coach_tools`
/ `app.dependencies` at runtime — both `backend/` and `mcp-server/` need to be on
`PYTHONPATH` together (see `mcp-server/Dockerfile`, which builds from the repo root for
exactly this reason).

### Auth: Supabase Auth as the OAuth 2.1 authorization server

The MCP spec's authorization model has three roles: the MCP client (Claude, etc.) is the
OAuth client, the MCP server is the OAuth **resource server**, and a separate
**authorization server** issues tokens. Astraphe uses **Supabase Auth (GoTrue) as that
authorization server** — it ships a purpose-built OAuth 2.1 Server mode
([Supabase docs](https://supabase.com/docs/guides/auth/oauth-server/mcp-authentication))
rather than standing up a bespoke one. This was chosen over a custom OAuth shim because
tokens it issues are ordinary Supabase JWTs, so the RLS policies that already scope every
other Astraphe request by the caller's own JWT apply automatically here too — there's no
separate authorization layer to write or trust.

Concretely:

- `supabase/config.toml` has `[auth.oauth_server] enabled = true`. Dynamic client
  registration (`allow_dynamic_registration`) is **on** in production — any MCP client can
  self-register without a maintainer manually issuing it a client ID/secret first. Local
  dev defaults to off (see the comment in `supabase/config.toml`); flip it locally if
  you're specifically testing the DCR flow itself.
- `mcp-server/astraphe_mcp/auth/token_verifier.py` validates bearer tokens the same way
  every other Astraphe request does: `db.auth.get_user(token)` (delegates verification to
  Supabase Auth itself — nothing here manually decodes a JWT).
- `mcp-server/astraphe_mcp/db.py` applies the caller's own token to a per-call Supabase
  client (`db.postgrest.auth(token)`) before any tool touches the database — the exact
  pattern `backend/app/dependencies.py:get_user_db()` uses. RLS enforces per-athlete
  scoping; the MCP server never needs the service-role key.

**One real constraint discovered building this**: GoTrue's OAuth Server only supports
standard OIDC scopes (`openid`, `profile`, `email`, `phone`) — requesting a custom scope
like `astraphe:read` at the `/oauth/authorize` step is rejected outright with
`unsupported scope`. There is currently no scope-based way to distinguish "read" access
from a future "write" access at the OAuth layer. Not needed yet (everything is read-only),
but Phase 3 (write tools) will need a different gating
mechanism than OAuth scopes — see [Rollout](#rollout).

### The consent screen

GoTrue's OAuth Server issues the redirect but doesn't render a consent UI — Supabase's own
docs say to build one. It lives in the mobile app at `mobile/src/routes/oauth/consent/`
(this exact path matters: it must match `authorization_url_path` in `supabase/config.toml`),
reusing the app's existing Supabase session rather than a separate login.

The actual contract, verified against a live local Supabase instance (not documented
anywhere with example requests at the time this was built, so recorded here in full):

1. GoTrue redirects the browser to `{site_url}{authorization_url_path}?authorization_id=<opaque_id>`
   — not the raw OAuth params (`client_id`, `scope`, etc.), just an opaque ID.
2. The consent page fetches the actual pending request:
   ```
   GET {SUPABASE_URL}/auth/v1/oauth/authorizations/{authorization_id}
   Headers: apikey: <anon key>, Authorization: Bearer <user's session access_token>
   ```
   Returns `{ authorization_id, redirect_uri, client: { id, name }, user: { id, email }, scope }`.
3. The user approves or denies:
   ```
   POST {SUPABASE_URL}/auth/v1/oauth/authorizations/{authorization_id}/consent
   Headers: apikey: <anon key>, Authorization: Bearer <user's session access_token>
   Body: { "action": "approve" }   // or "deny"
   ```
   Returns `{ "redirect_url": "<client's redirect_uri>?code=...&state=..." }` (or an error
   redirect on deny) — the page navigates the browser there to hand control back to the
   MCP client.

### Rate limiting

Every tool call goes through a per-athlete sliding-window limit (`MCP_RATE_LIMIT_RPM`,
default 30/min), enforced in `astraphe_mcp/tools/_call.py::call_handler()` before it
reaches `TOOL_HANDLERS`. This reuses `backend/app/core/rate_limiter.py`'s `RateLimiter`
class unmodified — Redis sorted-set sliding window when the **backend's** `REDIS_URL` is
configured, in-process fallback otherwise — with its own key namespace (`{athlete_id}:mcp:minute`)
so a user's MCP budget is tracked separately from their in-app coach quota
(`{athlete_id}:ai:minute`/`:ai:hour` in `backend/app/dependencies.py`). There's
deliberately no separate `REDIS_URL` setting on the MCP server itself — it shares the
backend's Redis instance and config on purpose, so set `REDIS_URL` on the **backend**
service if you want rate-limit state to survive a restart or be consistent across
multiple MCP server replicas.

This exists specifically because Dynamic Client Registration is on: with self-registration,
"who can call this server" is no longer gated by a maintainer manually vetting each OAuth
client, so a per-athlete request budget is the remaining backstop against a runaway or
malicious client hammering the database through someone's own account.

### Transport

Streamable HTTP only (`astraphe_mcp/asgi.py` — `mcp.streamable_http_app()`), the current
MCP spec's standard remote transport. No stdio (that's for local single-user servers with
no OAuth story) and no legacy bare-SSE transport.

`streamable_http_app()`'s DNS-rebinding protection defaults to accepting only `localhost`/
`127.0.0.1` `Host` headers when `transport_security` isn't passed explicitly — it can't
infer what public hostname the server will actually be reached as. `asgi.py` builds
`TransportSecuritySettings(allowed_hosts=...)` from `MCP_RESOURCE_URL` specifically to
avoid this; if you change how this server is exposed (a different domain, a path prefix,
etc.), make sure `MCP_RESOURCE_URL` still matches exactly, or every request 421s with
"Invalid Host header" despite auth working fine.

## Self-hosting

Requirements beyond a standard Astraphe self-host ([SETUP.md](./SETUP.md)):

1. Enable Supabase's OAuth Server on your own Supabase project (self-hosted or hosted) —
   see the [Auth](#auth-supabase-auth-as-the-oauth-21-authorization-server) section above
   for the config.toml flag. For a fresh local project (`supabase start`) this "just
   works" with zero extra key setup. **A self-hosted docker-compose/Kubernetes install
   started from an older `.env`/template may not** — GoTrue needs asymmetric (ES256 or
   RS256) signing to issue an OIDC ID token, and a JWT signing config that predates this
   feature typically only has the legacy symmetric `JWT_SECRET` (HS256) wired up. Symptom:
   `/oauth/token` 500s with `"HS256 is not supported for ID token signing"` right after a
   successful consent approval. Supabase's own self-hosted docs cover the fix — add an
   ES256 keypair via `JWT_KEYS`/`JWT_JWKS` env vars alongside the existing `JWT_SECRET`
   (kept for backward compatibility with existing sessions, zero downtime): see
   ["New API Keys and Asymmetric Authentication"](https://supabase.com/docs/guides/self-hosting/self-hosted-auth-keys).
   Check whether your `JWT_KEYS`/`JWT_JWKS` already exist as *empty* placeholder values
   before assuming you need to add new ones from scratch — a template that was applied
   without ever running the actual key-generation step looks configured but isn't.
2. If you're on a self-hosted docker-compose/Kubernetes install with Kong (or another API
   gateway) in front of Supabase Auth, check whether it gates `/auth/v1/*` behind a
   Supabase `apikey` header — Supabase's own default self-hosted `kong.yml` does, on the
   catch-all `/auth/v1/` route. That breaks every OAuth endpoint here (discovery,
   authorize, token, and especially `/auth/v1/oauth/clients/register` for DCR — not
   `/auth/v1/oauth/register`, verify the real path against your instance's own
   `.well-known/oauth-authorization-server` `registration_endpoint` rather than assuming),
   since a spec-compliant OAuth client like Claude has no reason to send a Supabase-specific
   header. Fix: add "open" routes (CORS plugin only, no key-auth) for those specific paths,
   mirroring whatever pattern your `kong.yml` already uses for other unauthenticated routes
   (e.g. `/auth/v1/verify`, `/auth/v1/.well-known/jwks.json`).
3. Copy `mcp-server/.env.example` to `mcp-server/.env` and fill in your Supabase project's
   URL/anon key, plus `MCP_ISSUER_URL` (your project's `/auth/v1`) and `MCP_RESOURCE_URL`
   (the public URL you'll expose this server at — see the [Transport](#transport) section's
   note on why this has to match exactly).
4. Register at least one OAuth client for testing if you're keeping Dynamic Client
   Registration off (see [Rollout](#rollout) — production runs with it on):
   ```
   POST {SUPABASE_URL}/auth/v1/admin/oauth/clients
   Headers: apikey: <service-role key>, Authorization: Bearer <service-role key>
   Body: { "client_name": "...", "redirect_uris": [...], "grant_types": ["authorization_code","refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": "none" }
   ```
5. Run it: `docker build -f mcp-server/Dockerfile -t astraphe-mcp .` from the **repo
   root** (not `mcp-server/` — the image needs `backend/app` too), then
   `docker run -p 8090:8090 --env-file mcp-server/.env astraphe-mcp`. Or run directly:
   `PYTHONPATH=backend:mcp-server uvicorn astraphe_mcp.asgi:app --app-dir mcp-server --port 8090`.
6. Streamable HTTP + OAuth needs a public HTTPS endpoint for a client like Claude Desktop
   to reach — put it behind whatever reverse proxy/tunnel you already use for the rest of
   your Astraphe deployment.

There is no tracked Kubernetes manifest for this service (same as `astraphe-api` — see
[DEPLOYMENT.md](./DEPLOYMENT.md)): the maintainer's reference instance has its own
`astraphe-mcp` Deployment/Service created once, out of band, on the cluster. CI then
builds+publishes the image (`build-mcp` job, tagged both `:latest` and by commit SHA) and,
once the `mcp-server` test job has passed, rolls it out (`deploy-mcp` job) via
`kubectl set image deployment/astraphe-mcp` to that commit-SHA tag — same pattern
`astraphe-api`'s own `deploy` job uses, and deliberately *not* just re-pointing at
`:latest`: a `kubectl set image` to an unchanged tag is a no-op to Kubernetes (no spec
diff means no rollout), so tagging by commit SHA is what makes each deploy actually land
without a manual `kubectl rollout restart`. If you're self-hosting, create the equivalent
for your own infrastructure — including scoping whatever CI ServiceAccount/Role you use to
the specific Deployment name(s) it needs to patch, not a wildcard.

## Rollout

1. **Phase 0 — done.** Supabase OAuth Server pre-flight: enabled on a local project,
   verified the full `backend/tests` suite and a real password-grant login still work
   against it (they do — nothing in `backend/` manually decodes a JWT, so the signing
   algorithm change is invisible to existing code).
2. **Phase 1 — done.** Read-only tools + auth, with Dynamic Client Registration off
   initially (test clients registered manually via the admin API above). Kept the surface
   area small while the auth flow got real-world use.
3. **Phase 2 — done.** Dynamic Client Registration is on in production — arbitrary MCP
   clients (not just manually-registered test ones) can self-register and connect. Landed
   together with the per-athlete rate limit this phase was gated on (see
   [Rate limiting](#rate-limiting)) — `astraphe_mcp/tools/_call.py::call_handler()` now
   calls `backend/app/core/rate_limiter.py`'s `RateLimiter` on every tool call.
4. **Phase 3.** Write tools (`log_workout`, `update_workout`, `log_biometrics`,
   `schedule_workout`, `update_planned_workout`, `delete_planned_workout`, `save_memory`,
   `update_memory`), gated separately from read access. Since GoTrue's OAuth Server
   doesn't support custom scopes (see [Auth](#auth-supabase-auth-as-the-oauth-21-authorization-server)),
   this needs a different gating mechanism than an `astraphe:write` OAuth scope — worth
   resolving before this phase starts, not during it. `clear_training_plans` (bulk-delete)
   is deliberately excluded from this list — if it's ever exposed via MCP, it needs its
   own narrower confirmation gate, not folded into general write access.
5. **Phase 4 (only if needed).** Promote the shared business logic out of `backend/app`
   into a real installable package if the `PYTHONPATH` coupling described in
   [Architecture](#architecture) becomes awkward to maintain. Not needed yet.

## Development

```bash
cd mcp-server
pip install -r ../backend/requirements.txt -r requirements.txt
cp .env.example .env   # point at your local Supabase (npx supabase start)
python -m pytest       # fully hermetic — no Supabase instance needed for tests
uvicorn astraphe_mcp.asgi:app --reload --port 8090
```

Tests live in `mcp-server/tests/`, reusing `backend/tests/conftest.py`'s hermetic fake
Supabase client so both suites agree on what "a fake athlete" looks like. Coverage for the
underlying tool handlers themselves (`handle_list_workouts`, etc.) already lives in
`backend/tests/test_coach_tools*.py` — since this server calls those functions unmodified,
`mcp-server/tests` only needs to cover its own glue: auth, athlete-id resolution/caching,
and the HTTP-level OAuth challenge/discovery shape.
