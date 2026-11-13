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
- Multisport activities (triathlon etc.) split into one workout per leg,
  transitions dropped.
- All-day heart rate (2-minute averages) stored per day in `heart_rate_series`,
  then used for workout auto-detection and day strain.
- Sleep stage segments and naps.
- Weigh-ins (Index scale or entered in Garmin Connect) into `weigh_ins`.
- Background poll loop for recent activities + biometrics, with a cooldown on
  429s (see Rate-Limit Mitigations).
- Mobile Connect/Unlink modal on Profile → Connected Apps.
- Sport mapping from Garmin Connect `activityType.typeKey` values.
- Canonical merge via the existing `processing.py` engine, which already
  treated `garmin` as a first-class source before this integration existed.

## Configuration

Backend settings (`backend/app/config.py`):

```env
# Active community-login integration
GARMIN_SYNC_POLL_HOURS=1
# Overrides the hours setting when set (production uses 15)
GARMIN_SYNC_POLL_MINUTES=
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
may land on different replicas: the pending login is shared through Redis,
encrypted (see Auth Flow below). No session affinity needed.

## API Routes

Connect / MFA / backfill ([`backend/app/routers/garmin_sync.py`](../backend/app/routers/garmin_sync.py)):

- `POST /v1/sync/garmin/connect` — body `{ username, password, days? }`.
  Returns `{ status: "success", ... }` or `{ mfa_required: true, state_token }`.
  Limited to 5 attempts per hour.
- `POST /v1/sync/garmin/connect/mfa` — body `{ state_token, mfa_code, days? }`.
  Limited to 10 attempts per hour.
- `POST /v1/sync/garmin/backfill?days=90` — manual re-sync for the authenticated
  athlete (1-365 days, 3 per hour).

Shared sync routes ([`backend/app/routers/sync.py`](../backend/app/routers/sync.py)):

- `GET /v1/sync/status` — includes `integrations.garmin.connected`.
- `DELETE /v1/sync/garmin` — unlink and drop the stored session.
- `POST /v1/sync/refresh-strain` — recompute day strain for every day with a
  workout or an all-day heart-rate series.

Legacy (unused) official webhook:

- `POST /v1/sync/garmin/webhook` — parses the official Health API push-notification
  shape. Returns 404 unless `GARMIN_WEBHOOK_SECRET` is set; nothing triggers it
  today (no OAuth1.0a authorize/callback route exists).

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
- `heart_rate_series`: one row per athlete, day and source with the day's
  all-day heart rate (`source='garmin'`, ranked above WHOOP and HealthKit when
  several exist).
- `workouts` with `source='hr_detected'`: workouts detected from that series
  (see Workout Detection below).
- `weigh_ins`: Garmin weigh-ins (`source='garmin'`). A weigh-in the athlete
  deleted stays deleted on re-sync.
- `biometrics`: sleep / HRV / resting HR / SpO2 / skin temp deviation merged
  per-field via `metric_sources` (a JSONB map of field → winning source) —
  there's no single row-level `source` column. A day where Garmin's HRV value
  wins shows `hrv_source='garmin'`. `spo2_pct` comes from `dailySleepDTO.avgSpO2`
  in the same sleep-summary call already made for sleep/HRV — no extra Garmin
  API request. A `0` (or negative / non-numeric / missing) `avgSpO2` is treated as
  no reading and not stored.
  `skin_temp_deviation_c` comes from the same call's top-level `avgSkinTempDeviationC`
  (a sibling of `dailySleepDTO`, not nested inside it), gated on `skinTempDataExists`
  since the value is stale/untrustworthy during Garmin's ~2-3 week baseline
  calibration window. This is a **deviation from the athlete's own baseline**
  (Garmin Connect's "Avg Skin Temp Change"), not an absolute reading like
  WHOOP's `skin_temp` (`skin_temp_celsius`, ~33-35°C) — so it doesn't merge
  directly with `skin_temp`. Instead, `process_and_save_biometrics` normalizes
  any absolute-reading source into the same signal by subtracting the average
  of that athlete's own `skin_temp` values over the 7 calendar days before the
  reading (today's own stored value and any 0/missing readings are excluded,
  matching the mobile recovery page's `baselineAvg7d`) before it
  reaches the merge step, so both Garmin's native deviation and WHOOP's
  computed one land in `skin_temp_deviation_c` as directly comparable deltas
  from personal baseline (see `docs/DATA_MODELS.md`). No official partner
  Health API access is needed for either field — both come from the same
  community-login `get_sleep_data()` call already in use.

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
  -> if MFA: hold the pending login (in-process + Redis), return { mfa_required, state_token }
       -> POST /v1/sync/garmin/connect/mfa { state_token, mfa_code, days }
  -> persist the encrypted session in oauth_tokens
  -> schedule background backfill
```

`garminconnect` (this version) does not depend on `garth`; login produces its
own small JSON token store (`client.client.dumps()` / `.loads()`) that this
integration encrypts before writing to `oauth_tokens.access_token`.

MFA pending state is held in an in-process dict keyed by `state_token` (5 min
TTL), and its serializable `client_state` (returned by `login()`, rebuilt by
`resume_login(client_state, code)` on any `Garmin` instance, garminconnect >= 0.3.20)
is shared through Redis as `garmin_mfa:{state_token}`, Fernet-encrypted with
`OAUTH_TOKEN_ENCRYPTION_KEY` (it holds session cookies) and taken once (GETDEL). So
the connect and MFA requests may land on different replicas. (Older library
versions kept the state only on the live client, whose `curl_cffi` session can't be
pickled; without Redis, only the replica that started the login can finish it.)

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
  -> per day: fetch sleep (incl. SpO2, skin temp deviation) / HRV / heart rates
       -> save sleep stage segments and naps
       -> save the all-day heart-rate series, run workout detection,
          refresh the day's strain
       -> process_and_save_biometrics
  -> fetch weigh-ins for the window (one call)
  -> recompute CTL/ATL once if detections changed
```

Polling:

- Started at FastAPI startup (`garmin.poll_loop`, wired in `main.py`).
- Cadence: `GARMIN_SYNC_POLL_MINUTES` when set (production uses 15), else
  `GARMIN_SYNC_POLL_HOURS` (default 1). Each tick reuses the stored session, so
  shorter cadences only spend the lighter API rate limit, not the login one.
- Window: recent 2 days (`POLL_WINDOW_DAYS`) of activities + biometrics —
  small on purpose, so a missed tick's Garmin-quota spend stays cheap.
- Multi-replica safe: each tick claims `oauth_tokens.refresh_lock_expires_at`
  per athlete (mirrors WHOOP's proactive-refresh claim pattern) before
  syncing, so only one replica works a given athlete at a time.

## Workout Detection And Day Strain

Garmin's `get_heart_rates` response (already fetched for resting HR) carries
the day's 2-minute heart rate. After saving it, `hr_activity_detection` looks
for unrecorded sessions: at least 10 minutes at or above 40% of heart-rate
reserve, cool spells up to 6 minutes bridged, never within ±5 minutes of a
recorded workout. Activities sync before biometrics, so recorded workouts are
already there to defer to; a recorded workout arriving later replaces an
overlapping detection. Runs where Garmin repeats the same value (sensor lost
contact) are dropped first (`heart_rate_series.drop_flatlines`).

The day's strain is then recomputed: workouts' zone minutes plus all-day
minutes at or above 50% of max HR outside workouts. Today's series grows
through the day, so each poll pass refreshes it. Formulas: `docs/ALGORITHMS.md`.

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
garmin > whoop > intervals_icu > strava > healthkit > manual > hr_detected
```

(Manual entry is trusted over every device for `weight_kg` and `height_cm`, since a user-entered
value is more reliable than any device estimate. `hr_detected` is last: any
recorded workout wins.)

## Sport Mapping

Garmin Connect `activityType.typeKey` (lowercase snake_case) → ASTRAPHE sports
(`backend/app/services/garmin.py::_SPORT_MAP`; extend that dict for keys not
yet covered — unknown keys fall back to `other`, they don't error):

| ASTRAPHE sport | Examples |
|---|---|
| `run` | `running`, `trail_running`, `treadmill_running`, `virtual_run` |
| `bike` | `cycling`, `indoor_cycling`, `mountain_biking`, `e_bike_ride` |
| `swim` | `swimming`, `lap_swimming`, `open_water_swimming` |
| `strength` | `strength_training`, `hiit`, `indoor_cardio`, `elliptical` |
| `row` | `rowing`, `indoor_rowing`, any key containing `rowing` |
| `mobility` | `yoga`, `pilates`, `stretching`, `breathwork` |
| `other` | `walking`, `hiking`, `multi_sport`, unknown keys |

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
  normally, so poll ticks inside that window skip the athlete rather than
  retrying into the same limit.
- During manual testing, avoid rapid reconnect loops against a personal account.

## Remaining Work

- Persist raw FIT to `fit_file_url` / storage (parsed streams already land).
- Strava-parity "refetch streams" control for Garmin-sourced workouts.
- Re-encrypt any pre-key plaintext `oauth_tokens` rows (any provider) after
  rolling out `OAUTH_TOKEN_ENCRYPTION_KEY` — new writes encrypt automatically;
  reads still accept legacy plaintext, but old rows stay plaintext until they
  are next written.
