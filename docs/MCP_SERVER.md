# MCP Server

Astraphe ships a standalone [MCP](https://modelcontextprotocol.io) (Model Context Protocol)
server that lets you connect your own Astraphe data — workouts, biometrics, training load,
coach memory — to any MCP-compatible AI client: Claude Desktop, claude.ai Connectors,
Claude Code, or anything else that speaks MCP over Streamable HTTP with OAuth.

It lives in `mcp-server/` as a separate service from the main API (`backend/`), with its
own Dockerfile, its own deployment, and its own auth story — see [Architecture](#architecture)
for why.

**Status: Phase 1 (read-only).** The tools below let a connected client read your data.
Nothing it can call writes anything back to Astraphe yet — see [Rollout](#rollout) for
what's coming.

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

## Tools (read-only, Phase 1)

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
  registration (`allow_dynamic_registration`) stays **off** through Phase 1 — see
  [Rollout](#rollout).
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
from a future "write" access at the OAuth layer. Phase 1 doesn't need this distinction
(everything is read-only), but Phase 3 (write tools) will need a different gating
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

### Transport

Streamable HTTP only (`astraphe_mcp/asgi.py` — `mcp.streamable_http_app()`), the current
MCP spec's standard remote transport. No stdio (that's for local single-user servers with
no OAuth story) and no legacy bare-SSE transport.

## Self-hosting

Requirements beyond a standard Astraphe self-host ([SETUP.md](./SETUP.md)):

1. Enable Supabase's OAuth Server on your own Supabase project (self-hosted or hosted) —
   see the [Auth](#auth-supabase-auth-as-the-oauth-21-authorization-server) section above
   for the config.toml flag. For local dev this "just works" with zero extra key setup —
   GoTrue provisions asymmetric (ES256) signing automatically when the feature is
   enabled, at least as of the GoTrue version this was built and tested against
   (`v2.188.1`); verify this still holds for whatever version you're running.
2. Copy `mcp-server/.env.example` to `mcp-server/.env` and fill in your Supabase project's
   URL/anon key, plus `MCP_ISSUER_URL` (your project's `/auth/v1`) and `MCP_RESOURCE_URL`
   (the public URL you'll expose this server at).
3. Register at least one OAuth client for testing (Dynamic Client Registration is off by
   default — see [Rollout](#rollout)):
   ```
   POST {SUPABASE_URL}/auth/v1/admin/oauth/clients
   Headers: apikey: <service-role key>, Authorization: Bearer <service-role key>
   Body: { "client_name": "...", "redirect_uris": [...], "grant_types": ["authorization_code","refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": "none" }
   ```
4. Run it: `docker build -f mcp-server/Dockerfile -t astraphe-mcp .` from the **repo
   root** (not `mcp-server/` — the image needs `backend/app` too), then
   `docker run -p 8090:8090 --env-file mcp-server/.env astraphe-mcp`. Or run directly:
   `PYTHONPATH=backend:mcp-server uvicorn astraphe_mcp.asgi:app --app-dir mcp-server --port 8090`.
5. Streamable HTTP + OAuth needs a public HTTPS endpoint for a client like Claude Desktop
   to reach — put it behind whatever reverse proxy/tunnel you already use for the rest of
   your Astraphe deployment.

There is no tracked Kubernetes manifest for this service (same as `astraphe-api` — see
[DEPLOYMENT.md](./DEPLOYMENT.md)): the maintainer's reference instance has its own
`astraphe-mcp` Deployment/Service created once, out of band, on the cluster, which CI then
patches the image on via `.github/workflows/deploy.yml`'s `build-mcp` job. If you're
self-hosting, create the equivalent for your own infrastructure.

## Rollout

1. **Phase 0 — done.** Supabase OAuth Server pre-flight: enabled on a local project,
   verified the full `backend/tests` suite and a real password-grant login still work
   against it (they do — nothing in `backend/` manually decodes a JWT, so the signing
   algorithm change is invisible to existing code).
2. **Phase 1 — this PR.** Read-only tools + auth, with Dynamic Client Registration off
   (test clients registered manually via the admin API above). Keeps the surface area
   small while the auth flow gets real-world use.
3. **Phase 2.** Turn on Dynamic Client Registration once Phase 1 has proven stable — this
   is the point arbitrary MCP clients (not just manually-registered test ones) can
   self-register and connect.
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
