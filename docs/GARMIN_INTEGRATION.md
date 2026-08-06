# Garmin Integration

## Current Status

Garmin Connect is implemented as a first-class integration using the community
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library (credential / MFA login via Garmin's mobile SSO). Official Garmin
Developer Program OAuth is partner-approval-only and not currently available for
self-serve signup; dormant OAuth1.0a config stubs remain in the codebase for a
possible future official path.

Implemented pieces:

- Credential connect with MFA resume (`POST /garmin/connect`, `/connect/mfa`).
- Encrypted session persistence in `oauth_tokens` — never the password.
- Historical backfill of activities and daily biometrics.
- FIT download + `fitdecode` parsing into Strava-shaped streams/laps.
- Hourly background poll loop for recent activities + biometrics, with a
  cooldown on 429s (see Rate-Limit Mitigations).
- Mobile Connect/Unlink modal on Profile → Connected Apps.
- Sport mapping from Garmin Connect `activityType.typeKey` values.
- Canonical merge via the existing `processing.py` engine, which already
  treated `garmin` as a first-class source before this integration existed.

## Configuration

Backend settings (`backend/app/config.py`):

```env
# Active community-login integration
GARMIN_SYNC_POLL_HOURS=1
# Fernet key encrypting oauth_tokens.access_token/refresh_token for every
# provider (WHOOP, Strava, intervals.icu, Garmin), not just this one —
# required in production. See app/services/token_crypto.py.
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
OAUTH_TOKEN_ENCRYPTION_KEY=

# Dormant official OAuth1.0a scaffolding (unused today)
GARMIN_CONSUMER_KEY=
GARMIN_CONSUMER_SECRET=
GARMIN_WEBHOOK_SECRET=
GARMIN_OAUTH_CONFIRM_URL=https://connect.garmin.com/oauthConfirm
```

No client id/secret is required for the active path. The poll loop runs its first
tick immediately on startup (self-heal), so a separate startup-backfill flag is
not needed.

**Multi-replica note:** `POST /garmin/connect` and `POST /garmin/connect/mfa`
must land on the same backend process for MFA-enabled accounts — the pending
login state lives only in that process's memory (see Auth Flow below). If this
service scales past one replica, enable session affinity (sticky routing) for
those two routes at the ingress/load balancer.

## API Routes

Connect / MFA / backfill ([`backend/app/routers/garmin_sync.py`](../backend/app/routers/garmin_sync.py)):

- `POST /v1/sync/garmin/connect` — body `{ username, password, days? }`.
  Returns `{ status: "success", ... }` or `{ mfa_required: true, state_token }`.
- `POST /v1/sync/garmin/connect/mfa` — body `{ state_token, mfa_code, days? }`.
- `POST /v1/sync/garmin/backfill?days=90` — manual re-sync for the authenticated athlete.

Shared sync routes ([`backend/app/routers/sync.py`](../backend/app/routers/sync.py)),
already provider-generic and needed no Garmin-specific changes:

- `GET /v1/sync/status` — includes `integrations.garmin.connected`.
- `DELETE /v1/sync/garmin` — unlink and drop the stored session.

Legacy (unused) official webhook:

- `POST /v1/sync/garmin/webhook` — parses the official Health API push-notification
  shape. Nothing can trigger it today (no OAuth1.0a authorize/callback route
  exists), left in place for a possible future official-API path.

## Data Model

Garmin contributes to:

- `oauth_tokens`: `provider='garmin'`, `access_token` = the serialized client
  session (`garminconnect`'s own internal token store — see Auth Flow — not
  `garth`, despite that being a common auth dependency for similar libraries;
  this version of `python-garminconnect` doesn't use it), Fernet-encrypted when
  `OAUTH_TOKEN_ENCRYPTION_KEY` is set (plaintext legacy rows still decrypt),
  `external_user_id` = Garmin display name. Every other provider's
  `access_token`/`refresh_token` is encrypted the same way — see
  `app/services/token_crypto.py`.
- `workouts`: canonical activity summary with `source='garmin'`, plus
  `garmin_activity_id` (unique fast-path dedup column, mirrors
  `strava_activity_id`), `elevation_gain_m`, and `calories`.
- `activity_streams` / `activity_laps`: FIT-derived streams and laps (same keys as Strava).
- `biometrics`: sleep / HRV / resting HR merged per-field via `metric_sources`
  (a JSONB map of field → winning source) — there's no single row-level
  `source` column. A day where Garmin's HRV value wins shows `hrv_source='garmin'`.

`workouts.source` and `biometrics.hrv_source` have included `'garmin'` since the
initial schema — no migration was needed for those. `garmin_activity_id` and
`calories` were new columns added in
`20260805150000_garmin_activity_id_and_calories.sql`.

## Auth Flow

Garmin has no self-serve OAuth for this product. Connection is credential-based:

```text
Mobile profile/connections → Connect Garmin
  -> POST /v1/sync/garmin/connect { username, password, days }
  -> backend calls garminconnect login (never stores the password)
  -> if MFA: hold the pending client in-process, return { mfa_required, state_token }
       -> POST /v1/sync/garmin/connect/mfa { state_token, mfa_code, days }
  -> persist the encrypted session in oauth_tokens
  -> schedule background backfill
```

`garminconnect` (this version) does not depend on `garth`; login produces its
own small JSON token store (`client.client.dumps()` / `.loads()`) that this
integration encrypts before writing to `oauth_tokens.access_token`.

MFA pending state (the live login client object) is held in an in-process dict
keyed by `state_token` (5 min TTL) — it cannot be handed off through Redis or any
other external store, because `garminconnect`'s MFA continuation only works
against the *same* in-memory client object, and that object holds a `curl_cffi`
HTTP session that is not picklable (verified empirically: attempting to pickle
it raises `TypeError: cannot pickle '_thread._local' object` once login has
progressed past the first strategy). This means the connect and MFA requests
for one login **must** land on the same backend process; see the multi-replica
note under Configuration.

Invalidate a compromised session by changing the Garmin password or signing out
of all devices in Garmin Connect account settings, then Unlink + reconnect in-app.

## Sync Flow

```text
Connect / backfill / poll tick
  -> restore persisted session (no username/password on routine sync)
  -> fetch activities by date window
  -> map summary → WorkoutPayload(source="garmin")
  -> process_and_save_workout (canonical merge/dedup)
  -> download ORIGINAL FIT → parse streams/laps → activity_streams / activity_laps
  -> fetch sleep / HRV / resting HR per day
  -> process_and_save_biometrics
```

Polling:

- Started at FastAPI startup (`garmin.poll_loop`, wired in `main.py`).
- Cadence: `GARMIN_SYNC_POLL_HOURS` (default 1h) — hourly, so sleep/recovery
  data is fresh soon after waking rather than stale for hours.
- Window: recent 2 days (`POLL_WINDOW_DAYS`) of activities + biometrics —
  small on purpose, so a missed tick's Garmin-quota spend stays cheap.
- Multi-replica safe: each tick claims `oauth_tokens.refresh_lock_expires_at`
  per athlete (mirrors WHOOP's proactive-refresh claim pattern) before
  syncing, so only one replica works a given athlete at a time.

## Deduplication

Same workout can arrive from Strava, Garmin, WHOOP, intervals.icu, HealthKit, or
manual entry. Cross-source merge uses the existing interval-overlap + field-quality
logic in `processing.py`. Garmin is a first-class source in `SOURCE_PRIORITY` and
the per-field quality tables.

Exact fast paths:

- `strava_activity_id`
- `garmin_activity_id`

Then fuzzy ±10 minute / duration-tolerance merge. Fuzzy hits also backfill the
Garmin/Strava id columns when missing.

General priority, both for workout fields and biometrics (`SOURCE_PRIORITY` in
`processing.py`), highest to lowest:

```
garmin > whoop > intervals_icu > strava > healthkit > manual
```

(Manual entry is trusted over everything for `weight_kg`/`height_cm` specifically —
those are the one exception, since a user-entered value is more reliable than
any device estimate.)

## Sport Mapping

Garmin Connect `activityType.typeKey` (lowercase snake_case) → ASTRAPHE sports
(`backend/app/services/garmin.py::_SPORT_MAP`; extend that dict for keys not
yet covered — unknown keys fall back to `other`, they don't error):

| ASTRAPHE sport | Examples |
|---|---|
| `run` | `running`, `trail_running`, `treadmill_running`, `virtual_run` |
| `bike` | `cycling`, `indoor_cycling`, `mountain_biking`, `e_bike_ride` |
| `swim` | `swimming`, `lap_swimming`, `open_water_swimming` |
| `strength` | `strength_training`, `hiit`, `indoor_cardio` |
| `row` | `rowing`, `indoor_rowing` |
| `mobility` | `yoga`, `pilates`, `stretching` |
| `other` | `walking`, `hiking`, unknown keys |

## Rate-Limit Mitigations

Garmin's SSO endpoint aggressively rate-limits repeated *logins* (account-level
429 lockouts of 48+ hours are documented after failed/rapid login attempts).
General API calls (once already logged in) are a separate, lighter-weight
limit, but `garminconnect` never retries a 429 on either — by design, it treats
401/429/4xx as "deterministic and caller-actionable" and fails fast rather than
retrying. Mitigations:

- Persist and reuse the session on every poll/backfill; never re-login with
  username/password on a routine sync.
- Pace requests during backfill/poll (`GARMIN_REQUEST_GAP_S`, 1s between calls).
- Keep the poll window small (recent days only, not a full re-backfill).
- On any 429 (`GarminRateLimitedError`), stop the current sync pass
  immediately instead of continuing to the next activity/day at the same
  pace — whatever was already saved is kept, but no further Garmin calls are
  made for that pass.
- The poll loop then holds that athlete's sync lock for
  `GARMIN_RATE_LIMIT_COOLDOWN_SEC` (30 minutes) instead of releasing it
  normally, so the *next* poll tick (an hour later, by default) skips that
  athlete rather than immediately retrying into the same limit.
- During manual testing, avoid rapid reconnect loops against a personal account.

## Remaining Work

- Persist raw FIT to `fit_file_url` / storage (parsed streams already land).
- Strava-parity "refetch streams" control for Garmin-sourced workouts.
- Re-encrypt any pre-key plaintext `oauth_tokens` rows (any provider) after
  rolling out `OAUTH_TOKEN_ENCRYPTION_KEY` — new writes encrypt automatically;
  reads still accept legacy plaintext, but old rows stay plaintext until they
  are next written.
