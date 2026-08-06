# Add Garmin Connect Integration

## Context

ASTRAPHE already integrates WHOOP, Strava, and intervals.icu, each feeding a shared canonical `workouts`/`biometrics` model. Garmin is the natural next source — many athletes' primary device — but Garmin's real Developer Program (`developer.garmin.com/gc-developer-program`) is partner-approval-only, restricted to legal business entities, and as of 2026 is reportedly not accepting new signups at all, with no published reopen date. There is no self-serve path for an individual/small company to get official API access.

The codebase already has a half-built attempt at the *official* Garmin OAuth1.0a flow: `GARMIN_CONSUMER_KEY`/`GARMIN_CONSUMER_SECRET`/`GARMIN_OAUTH_CONFIRM_URL` config stubs and a `POST /v1/sync/garmin/webhook` receiver in `sync.py` that parses the official push-notification payload shape — but no authorize/callback routes were ever added, so it's dead code that nothing can trigger. Rather than chase official access, this plan uses the community-maintained `python-garminconnect` library (wraps Garmin's mobile-app SSO login) to connect via the user's own Garmin username/password, matching how tools like this are commonly used for personal-account access. The dead OAuth1.0a scaffold is left alone (harmless, revivable later if partner access is ever granted).

Convenient finding from exploration: the canonical workout/biometrics merge engine (`SOURCE_PRIORITY`, per-field quality tables, `workouts.source` and `biometrics.hrv_source` CHECK constraints, `GET /v1/sync/status`, `DELETE /v1/sync/{provider}`) was already built with `garmin` as a first-class source from day one. Onboarding Garmin needs **no changes** to `processing.py`'s dedup logic and **no schema migrations** for those constraints — only a service to actually produce the data.

Scope for v1 (confirmed with user): **workouts (with streams/laps/GPS/power, matching Strava's richness) and daily biometrics (sleep, HRV, resting HR)** — comparable coverage to WHOOP. Connection uses an in-app username/password (+ MFA) form, not an OAuth button; only the resulting session token is persisted, never the password.

## Tool choice: `python-garminconnect`, not `GarminDB`

- **[python-garminconnect](https://github.com/cyberjunky/python-garminconnect)** (PyPI `garminconnect`, MIT, ~2.8k★, actively developed): a thin API client wrapping `garth` for Garmin's mobile-SSO login (incl. MFA), exposing activities, health metrics, and raw activity file downloads (FIT/TCX/GPX/KML via `download-service` endpoints). This is a **library** meant to be imported into another app — the right shape for a backend integration.
- **[GarminDB](https://github.com/tcgoetz/GarminDB)**: a standalone CLI/analytics tool that owns its own SQLite database and is meant to be run as a personal data pipeline (`garmindb_cli.py --all --download --import --analyze`), not imported as a dependency. Wrong shape for this codebase — rejected.
- **Known operational risk**: Garmin's SSO endpoint aggressively rate-limits repeated logins — accounts can get 429-blocked for 48+ hours after a few failed/rapid login attempts (this is an account-level block, not IP-level). Mitigation: persist `garth`'s session/token state after the first login and reuse it on every subsequent sync; only fall back to a fresh username/password login when the stored session is genuinely invalid. Keep the polling cadence conservative (see below).
- New deps for `backend/requirements.txt`: `garminconnect` (pulls in `garth`), `fitdecode` (actively maintained FIT-file parser; `fitparse` is more dormant — used to decode the downloaded FIT files into per-second streams, since unlike Strava, Garmin's community API doesn't hand back stream JSON directly).

## Backend changes

### 1. New service: `backend/app/services/garmin.py`
Mirrors the shape of `strava.py`/`intervals_icu.py` (one file per provider: auth, fetch, mapping, ingest-orchestration).

- `login(username, password)` — wraps `garminconnect.Garmin(...).login()`; returns either a ready client or an MFA-pending marker (garth's login flow can return a client_state needing `resume_login(client_state, mfa_code)`).
- `resume_mfa(client_state, mfa_code)` — completes MFA.
- `serialize_session(client)` / `restore_session(blob)` — persist/restore `garth`'s token store as an opaque JSON blob (this is what gets saved in `oauth_tokens`, not the password).
- `get_valid_client(athlete_id, db)` — loads the persisted session, restores the `garth` client; re-persists the blob after use in case `garth` silently rotated the internal OAuth2 token.
- `map_garmin_connect_sport(type_key)` — new mapping table for `activityType.typeKey` values returned by `get_activities`/`get_activities_by_date` (lowercase snake_case: `running`, `cycling`, `trail_running`, `strength_training`, `indoor_cycling`, `open_water_swimming`, `hiking`, `walking`, etc.), feeding into the existing `normalize_sport()` in `processing.py`. This supersedes the dead `map_garmin_sport()` in `sync.py`, which was written for the official API's different (uppercase) enum — plan to fold that one into this new mapper once the webhook path is confirmed unused, rather than maintaining two.
- `build_workout_payload(activity)` — maps a Garmin activity summary (distance, duration, avg/max HR, avg power, normalized power, calories, elevation) into `WorkoutPayload(source="garmin", ...)`, parallel to `strava.py`'s equivalent.
- `download_and_parse_fit(client, activity_id)` — calls the library's original-format download, unzips, parses with `fitdecode`, and shapes `record` messages into the **same stream-dict keys Strava already uses** (`time`, `heartrate`, `watts`, `cadence`, `velocity_smooth`, `altitude`, `distance`, `latlng`) plus a laps list — so `stream_storage.py`, `activity_laps`, and every existing chart in `activity_detail.py`/the mobile workout-detail screen need zero changes.
- `sync_activities_for_athlete(athlete_id, db, start_date, end_date)` — fetch list, for each unseen `external_id` build+store the workout via `processing.process_and_save_workout`, then hydrate streams/laps. Mirrors the Strava backfill loop.
- `fetch_and_store_biometrics_for_day(athlete_id, db, day)` — wraps `get_sleep_data`/`get_hrv_data`/`get_rhr_day` into `DailyBiometrics(source="garmin", ...)` (fields: `sleep_duration_min`, `sleep_deep_pct`/`rem_pct`/`light_pct`/`awake_pct`, `sleep_bedtime`/`sleep_wakeup`, `hrv_rmssd`, `resting_hr`), calls `processing.process_and_save_biometrics`.
- `backfill_historical_data(athlete_id, db, days=90)` — top-level entry point mirroring `strava.backfill_historical_data`/`whoop_backfill.backfill_historical_data`, with a small delay between Garmin calls to stay under rate limits.

### 2. Router: new `backend/app/routers/garmin_sync.py` (mounted at the same `/v1/sync` prefix)
`sync.py` is already 1700+ lines; splitting Garmin out avoids growing it further. Endpoints, following the `intervals_icu_connect` precedent (credential-based, no OAuth redirect):

- `POST /garmin/connect` — body `{username, password, days}`. Calls `garmin.login()`. If MFA is required, returns `{mfa_required: true, state_token}` (the pending `client_state` held server-side keyed by a short-lived token — in Redis if available, else in-process — **never written to `oauth_tokens`**). Otherwise persists the serialized session + `external_user_id` (Garmin profile id) into `oauth_tokens` (`provider='garmin'`), schedules `backfill_historical_data` via `BackgroundTasks`, returns the same shape as `intervals_icu_connect`.
- `POST /garmin/connect/mfa` — body `{state_token, mfa_code}`. Completes login, then does the same persist+schedule+response.
- `POST /garmin/backfill?days=90` — manual re-sync, mirrors `strava_backfill_now`/`intervals_icu_backfill_now`.
- `GET /status` and `DELETE /{provider}` in `sync.py` already work for `garmin` untouched (both are already provider-generic).
- Leave the existing `POST /garmin/webhook` in `sync.py` as-is — dead but harmless, revivable if official access ever materializes.

### 3. Periodic sync loop
Garmin has no webhook, so — like intervals.icu but automated — add an `asyncio` loop started at FastAPI startup (`backend/app/main.py`, same `@app.on_event("startup")` mechanism as `token_refresh_loop`), running every `GARMIN_SYNC_POLL_HOURS` (config default **1h**, per user request — hourly so sleep/recovery data is fresh soon after waking, not stale for up to 6 hours): iterate connected Garmin athletes, pull a short recent window (last ~2 days of activities + today's biometrics), stagger/jitter per athlete, and wrap each athlete in try/except so one 429/lockout doesn't stop the loop. `POST /garmin/backfill` remains available for on-demand "sync now" from the app.

Hourly polling raises the login/rate-limit stakes from the risk noted above — mitigate by making the loop reuse the persisted `garth` session on every tick (never re-authenticating with username/password on a routine poll) and by fetching the smallest useful window per tick rather than a full re-backfill, so a stolen hour of quota isn't wasted re-fetching old data.

### 4. Config (`backend/app/config.py`, `.env.example`)
No client id/secret needed (credential-based, not OAuth). Add:
- `GARMIN_SYNC_POLL_HOURS: int = 1` (hourly, so sleep/recovery data is ready shortly after waking)
- `GARMIN_STARTUP_BACKFILL_ENABLED` (optional, mirrors the WHOOP/Strava startup self-heal pattern)

Leave the existing unused `GARMIN_CONSUMER_KEY`/`CONSUMER_SECRET`/`OAUTH_CONFIRM_URL` in place, untouched.

### 5. Migrations
None required for `workouts.source` (`'garmin'` has been valid since `20260427000000_initial_schema.sql`) or `biometrics.hrv_source` (also includes `'garmin'` since the same initial migration) or `oauth_tokens.provider` (no CHECK constraint). Verify this holds during implementation before assuming it — confirmed by reading the migration files, but re-check `supabase/migrations/` for anything added after this exploration. A migration would only be needed if a `garmin_activity_id` fast-path dedup column (analogous to `strava_activity_id`) is added later — not required for v1 since the fuzzy interval-overlap dedup in `processing.py` already covers Garmin.

### 6. Security note (explicit tradeoff, not silently assumed)
`oauth_tokens.access_token`/`refresh_token` are stored in plaintext today for every provider (no encryption anywhere in the codebase) — Garmin's session blob can follow that same established pattern for v1. But a Garmin session is closer to full account access than a scoped OAuth token, so:
- Never persist the raw password beyond the in-memory lifetime of the `/garmin/connect` request.
- Document (in the new integration doc and in-app copy) that a user can invalidate a compromised session by changing their Garmin password or signing out of all devices in Garmin Connect account settings.
- Flag encrypting `oauth_tokens.access_token` for `provider='garmin'` (e.g. Fernet, key from a new env var) as a near-term fast-follow, even if not done in v1.

### 7. Docs
Add `docs/GARMIN_INTEGRATION.md` following `docs/STRAVA_INTEGRATION.md`'s structure (Status / Configuration / Routes / Data Model / Auth Flow / Sync Flow / Dedup / Sport Mapping / Remaining Work), explicitly noting the credential-based auth model and rate-limit mitigations.

## Mobile changes

### 1. `mobile/src/routes/profile/connections/+page.svelte`
Garmin already has a UI placeholder here (icon, "Connected" pill wiring, `toggleIntegration('garmin')` stub) — replace the "Coming soon" pill with a real flow:
- Since Garmin isn't OAuth, reuse the **intervals.icu modal pattern** (not `openOAuthAuthorize`): a `showGarminModal` with Username + Password (`type="password"`) fields, Cancel/Connect footer, calling a new `connectGarmin({ username, password, days })`.
- Handle the MFA branch: if the connect call returns `{mfa_required: true, state_token}`, swap the modal to an MFA-code input step, submit via `connectGarminMfa({ state_token, mfa_code })`.
- Update `toggleIntegration`'s `garmin` branch to open this modal instead of the current sleep-stub.
- Reconcile the Garmin brand color mismatch already present between this page (`#00A0E9`) and `DataSources.svelte` (`#009CDE`) while touching this code.

### 2. `mobile/src/lib/services/activityService.ts` (or wherever `connectIntervalsIcu` lives)
Add `connectGarmin` / `connectGarminMfa` functions following the same fetch-wrapper pattern as `connectIntervalsIcu`.

### 3. No changes needed
`training/+page.svelte`'s generic `isConnected` check, `DataSources.svelte` (Garmin entry already present), and the dashboard/recovery/sleep empty-state copy (already name-drops Garmin) all work unchanged once real data starts flowing in through `syncStatus.integrations.garmin`.

## Testing / Verification

- New `backend/tests/test_garmin.py` mirroring `backend/tests/test_intervals_icu.py`: mock the `garminconnect.Garmin` client, test `map_garmin_connect_sport`, test FIT parsing against a small fixture `.fit` file with `fitdecode`, test `build_workout_payload`.
- Manual end-to-end: connect a real Garmin account through the new modal (including an MFA-enabled account, since that's a distinct code path), confirm the activity shows in `GET /v1/sync/status` and streams/laps render on the workout detail screen, confirm a Garmin activity that overlaps an existing Strava/WHOOP entry for the same session merges into a single canonical `workouts` row rather than duplicating (the existing `backend/scripts/merge_overlapping_workouts.py` can clean up any historical dupes if needed).
- During initial backfill testing, watch logs for 429s from Garmin's SSO/API — if hit, stop and rely on the persisted session rather than repeated logins; this is the single biggest way to burn a test account's access for 48+ hours.

## Suggested sequencing

1. Backend service + connect/MFA/backfill routes + tests — verify via direct HTTP calls with a personal Garmin account before touching mobile.
2. Mobile connect modal + MFA step.
3. Enable the periodic poll loop.
4. Docs.
5. Fast-follows: token encryption for the Garmin session blob, `garmin_activity_id` fast-path column, Strava-parity "refetch streams" button.
