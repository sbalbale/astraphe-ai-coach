# Garmin Integration

## Current Status

Garmin Connect is implemented as a first-class integration using the community
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library (credential / MFA login via Garmin's mobile SSO). Official Garmin
Developer Program OAuth is partner-approval-only and not currently available for
self-serve signup; dormant OAuth1.0a config stubs remain in the codebase for a
future official path.

Implemented pieces:

- Credential connect with MFA resume (`POST /garmin/connect`, `/connect/mfa`).
- Session persistence in `oauth_tokens` (garth token blob only — never the password).
- Historical backfill of activities and daily biometrics.
- FIT download + `fitdecode` parsing into Strava-shaped streams/laps.
- Hourly background poll loop for recent activities + today's biometrics.
- Mobile Connect/Unlink modal on Profile → Connected Apps.
- Sport mapping from Garmin Connect `activityType.typeKey` values.
- Canonical merge via existing `processing.py` (no schema migration required).

## Configuration

Backend settings:

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

Shared sync routes ([`backend/app/routers/sync.py`](../backend/app/routers/sync.py)):

- `GET /v1/sync/status` — includes `integrations.garmin.connected`.
- `DELETE /v1/sync/garmin` — unlink and drop the stored session.

Legacy (unused) official webhook:

- `POST /v1/sync/garmin/webhook` — left in place for a future official API path.

## Data Model

Garmin contributes to:

- `oauth_tokens`: `provider='garmin'`, `access_token` = Fernet-encrypted garth/DI
  session blob when `OAUTH_TOKEN_ENCRYPTION_KEY` is set (plaintext legacy rows
  still decrypt), `external_user_id` = Garmin display name. Every other
  provider's `access_token`/`refresh_token` is encrypted the same way — see
  `app/services/token_crypto.py`.
- `workouts`: canonical activity summary with `source='garmin'`, plus
  `garmin_activity_id` (unique fast-path), `elevation_gain_m`, and `calories`.
- `activity_streams` / `activity_laps`: FIT-derived streams and laps (same keys as Strava).
- `biometrics`: daily sleep / HRV / resting HR with `source='garmin'`.

`workouts.source` and `biometrics.hrv_source` have included `'garmin'` since the
initial schema. `garmin_activity_id` and `calories` were added in
`20260805150000_garmin_activity_id_and_calories.sql`.

## Auth Flow

Garmin has no self-serve OAuth for this product. Connection is credential-based:

```text
Mobile profile/connections → Connect Garmin
  -> POST /v1/sync/garmin/connect { username, password, days }
  -> backend calls garminconnect login (never stores password)
  -> if MFA: hold the pending client in-process, return { mfa_required, state_token }
       -> POST /v1/sync/garmin/connect/mfa { state_token, mfa_code, days }
  -> persist encrypted session blob in oauth_tokens
  -> schedule background backfill
```

MFA pending state (the live login client) is held in an in-process dict keyed by
`state_token` (5 min TTL) — it cannot be handed off through Redis or any other
store, because `garminconnect`'s MFA continuation only works against the same
in-memory client object, and that object holds a `curl_cffi` HTTP session that
is not picklable. This means the connect and MFA requests for one login **must**
land on the same backend process; see the multi-replica note under
Configuration.

Invalidate a compromised session by changing the Garmin password or signing out
of all devices in Garmin Connect account settings, then Unlink + reconnect in-app.

## Sync Flow

```text
Connect / backfill / poll tick
  -> restore persisted garth session (no username/password on routine sync)
  -> fetch activities by date window
  -> map summary → WorkoutPayload(source="garmin")
  -> process_and_save_workout (canonical merge/dedup)
  -> download ORIGINAL FIT → parse streams/laps → activity_streams / activity_laps
  -> fetch sleep / HRV / resting HR per day
  -> process_and_save_biometrics
```

Polling:

- Started at FastAPI startup (`garmin_poll_loop`).
- Cadence: `GARMIN_SYNC_POLL_HOURS` (default 1).
- Window: recent ~2 days of activities + today's biometrics.
- Multi-replica safe via `oauth_tokens.refresh_lock_expires_at` claim per athlete.

## Deduplication

Same workout can arrive from Strava, Garmin, WHOOP, intervals.icu, HealthKit, or
manual entry. Cross-source merge uses the existing interval-overlap + field-quality
logic in `processing.py`. Garmin is a first-class source in `SOURCE_PRIORITY` and
per-field quality tables.

Exact fast paths:

- `strava_activity_id`
- `garmin_activity_id`

Then fuzzy ±10 minute / duration-tolerance merge. Fuzzy hits also backfill the
Garmin/Strava id columns when missing.

General priorities:

- Recovery / sleep / daily strain: WHOOP preferred when present.
- Power / GPS / cadence / streams / elevation: Strava and Garmin are strong sources.

## Sport Mapping

Garmin Connect `activityType.typeKey` (lowercase snake_case) → ASTRAPHE sports:

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

Garmin's SSO aggressively rate-limits repeated logins (account-level 429 lockouts
of 48+ hours are common after failed/rapid attempts). Mitigations:

- Persist and reuse the garth session on every poll/backfill; never re-login with
  username/password on a routine tick.
- Keep poll windows small (recent days only).
- Stagger/jitter athletes; wrap each athlete in try/except so one failure does
  not stop the loop.
- During testing, avoid rapid reconnect loops against a personal account.

## Remaining Work

- Persist raw FIT to `fit_file_url` / storage (parsed streams already land).
- Strava-parity "refetch streams" control for Garmin-sourced workouts.
- Re-encrypt any pre-key plaintext `oauth_tokens` rows (any provider) after
  rolling out `OAUTH_TOKEN_ENCRYPTION_KEY` — new writes encrypt automatically;
  reads still accept legacy plaintext, but old rows stay plaintext until they
  are next written.
