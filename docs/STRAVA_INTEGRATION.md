# Strava Integration

## Current Status

Strava is implemented as a first-class integration in the backend (`backend/app/services/strava.py`, `backend/app/routers/sync.py`, `backend/app/routers/activity_detail.py`).

Implemented pieces:

- OAuth 2.0 authorize/callback flow with a signed `state`.
- Webhook verification and event ingestion.
- Owner verification using the authenticated Strava athlete ID.
- Token refresh and storage in `oauth_tokens`.
- Manual backfill, plus a startup backfill of the last 24 hours to recover webhooks missed during a deploy or restart.
- Activity detail ingestion into `workouts`.
- Stream and lap storage in `activity_streams` and `activity_laps`.
- Activity detail routes for streams, laps, intervals, refetch/hydration, and zones.
- Sport normalization to ASTRAPHE sports, including `row`.

## Configuration

Backend settings:

```env
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_WEBHOOK_VERIFY_TOKEN=
STRAVA_WEBHOOK_SUBSCRIPTION_ID=
STRAVA_STARTUP_BACKFILL_ENABLED=true
STRAVA_STARTUP_BACKFILL_HOURS=24
APP_BASE_URL=http://localhost:8000
MOBILE_DEEP_LINK_SCHEME=astraphe
```

When `STRAVA_WEBHOOK_SUBSCRIPTION_ID` is set, webhook events from any other subscription are dropped. `backend/app/services/strava_webhook_sub.py` lists and registers push subscriptions against `{APP_BASE_URL}/v1/sync/strava/webhook`.

Set the Strava app callback domain to the production API host. Locally, expose the backend with ngrok or Cloudflare Tunnel and update `APP_BASE_URL` to the public URL when testing OAuth/webhooks.

## API Routes

OAuth:

- `GET /v1/sync/oauth/strava/authorize`
- `GET /v1/sync/oauth/strava/callback`

Webhooks:

- `GET /v1/sync/strava/webhook`: subscription verification.
- `POST /v1/sync/strava/webhook`: activity event receiver.

Backfill and status:

- `POST /v1/sync/strava/backfill?days=90` (3 per hour)
- `GET /v1/sync/status`
- `DELETE /v1/sync/strava`

Activity detail:

- `GET /v1/activities/{workout_id}/detail` (preferred — streams, laps, intervals, zones)
- `GET /v1/activities/{workout_id}/streams`
- `GET /v1/activities/{workout_id}/laps`
- `GET /v1/activities/{workout_id}/intervals`
- `POST /v1/activities/{workout_id}/hydrate-streams` (30 per hour)
- `POST /v1/activities/{workout_id}/refetch-strava` (20 per hour)
- `GET /v1/activities/{workout_id}/zones`

## Data Model

Strava contributes to these tables:

- `oauth_tokens`: provider `strava`, access/refresh token, expiry, scopes, and provider metadata.
  `access_token`/`refresh_token` are encrypted at rest with `OAUTH_TOKEN_ENCRYPTION_KEY`
  (Fernet; see `backend/app/services/token_crypto.py`) when that key is configured —
  legacy plaintext rows still read correctly.
- `workouts`: canonical activity summary with `source='strava'`.
- `activity_streams`: per-second stream arrays and metadata.
- `activity_laps`: lap/split detail rows.

`workouts.source` accepts `strava`. `workouts.sport` accepts `run`, `bike`, `swim`, `strength`, `row`, `mobility`, and `other`.

## OAuth Flow

```text
Mobile profile/connections screen
  -> GET /v1/sync/oauth/strava/authorize
  -> Strava consent
  -> GET /v1/sync/oauth/strava/callback?code=...
  -> backend exchanges code for token
  -> backend stores token + owner mapping
  -> backend redirects to app/web return target
  -> optional recent activity import/backfill
```

The authorize URL requests `activity:read_all,profile:read_all` with `approval_prompt=force`, so Strava always shows the consent screen.

## Webhook Flow

```text
Strava activity event
  -> GET challenge during subscription setup (checks STRAVA_WEBHOOK_VERIFY_TOKEN)
  -> POST create/update/delete events
  -> drop events for another subscription_id (when configured) or an unknown owner
  -> map owner_id to the stored Strava token's athlete
  -> create/update: fetch activity detail in the background, upsert workout + streams/laps
  -> delete: clear strava_activity_id on that athlete's workout (the workout row stays)
```

Strava webhooks are intentionally event-driven. Apart from the startup backfill, Strava is not polled on a schedule.

## Streams And Laps

Streams are used for intra-workout detail such as:

- `time`
- `heartrate`
- `watts`
- `cadence`
- `velocity_smooth`
- `altitude`
- `distance`
- `latlng`
- `grade_smooth`

Laps are stored separately so workout detail screens can show interval/split summaries without loading the full stream payload.

Detail, stream and zone responses are cached in Redis when it is configured.

## Deduplication

The same workout session can arrive from Strava, Garmin, WHOOP, intervals.icu,
HealthKit, or manual entry. `processing.py`'s canonical merge engine
(`_find_or_create_canonical_workout_sync`) handles this for every source, not
just Strava:

- Exact fast paths: `strava_activity_id` and `garmin_activity_id` (both unique
  columns on `workouts`) match a session to its existing canonical row instantly.
- Otherwise, fuzzy matching scores candidate workouts within a ±10 minute
  window by interval overlap, sport compatibility, and duration ratio, and
  merges into the best match.
- On merge, `source_ids` (JSONB) accumulates every provider's id for that
  session, and `primary_source` is elevated by `SOURCE_PRIORITY` order —
  higher-priority sources' data wins per field, via the `_QUALITY_FIELD_SOURCES`
  table, rather than one source unconditionally overwriting another.

General source priority, both for workout fields and biometrics
(`SOURCE_PRIORITY` in `processing.py`), highest to lowest:

```
garmin > whoop > intervals_icu > strava > healthkit > manual > hr_detected
```

(Manual entry is trusted over every device for `weight_kg`/`height_cm`
specifically — a user-entered value is more reliable than any device estimate.
`hr_detected` workouts, found in all-day heart rate, yield to any recorded one.)

## Sport Mapping

Strava sport types are normalized to ASTRAPHE's canonical sport tokens (`SPORT_CANONICAL` in `processing.py`, case-insensitive):

| ASTRAPHE sport | Examples |
|---|---|
| `run` | Run, TrailRun, VirtualRun |
| `bike` | Ride, VirtualRide, EBikeRide |
| `row` | Rowing, VirtualRow, IndoorRow |
| `swim` | Swim, OpenWaterSwim, VirtualSwim |
| `strength` | WeightTraining, Workout, Crossfit |
| `mobility` | Yoga, Stretching, Pilates |
| `other` | Walk, Hike, unknown types |

## Remaining Work

The backend has the core Strava plumbing. Product polish remains around:

- Richer mobile workout detail visualizations.
- Deeper cross-source merge rules for near-duplicate workouts.
- User-facing repair flows for failed stream/lap hydration.
- Segment/best-effort analysis.
- More explicit rate-limit backoff for large historical imports.
