# Strava Integration

## Current Status

Strava is implemented as a first-class integration in the backend. It is no longer just a plan.

Implemented pieces:

- OAuth 2.0 authorize/callback flow.
- Webhook verification and event ingestion.
- Owner verification using the authenticated Strava athlete ID.
- Token refresh and storage in `oauth_tokens`.
- Recent activity backfill.
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
APP_BASE_URL=http://localhost:8000
MOBILE_DEEP_LINK_SCHEME=astraphe
```

Set the Strava app callback domain to the production API host. Locally, expose the backend with ngrok or Cloudflare Tunnel and update `APP_BASE_URL` to the public URL when testing OAuth/webhooks.

## API Routes

OAuth:

- `GET /v1/sync/oauth/strava/authorize`
- `GET /v1/sync/oauth/strava/callback`

Webhooks:

- `GET /v1/sync/strava/webhook`: subscription verification.
- `POST /v1/sync/strava/webhook`: activity event receiver.

Backfill and status:

- `POST /v1/sync/strava/backfill?days=90`
- `GET /v1/sync/status`
- `DELETE /v1/sync/strava`

Activity detail:

- `GET /v1/activities/{workout_id}/detail` (preferred — streams, laps, intervals, zones)
- `GET /v1/activities/{workout_id}/streams`
- `GET /v1/activities/{workout_id}/laps`
- `GET /v1/activities/{workout_id}/intervals`
- `POST /v1/activities/{workout_id}/hydrate-streams`
- `POST /v1/activities/{workout_id}/refetch-strava`
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

Requested scopes should include activity read access. Use the narrowest scopes that support the product flow being tested.

## Webhook Flow

```text
Strava activity event
  -> GET challenge during subscription setup
  -> POST create/update/delete events
  -> verify token/subscription config
  -> map owner_id to stored Strava token
  -> fetch activity detail
  -> upsert workout and related stream/lap data
```

Strava webhooks are intentionally event-driven. Do not poll Strava for new activities on a schedule.

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

Redis may cache high-read stream/zone responses when configured.

## Deduplication

The current integration normalizes Strava activities into canonical `workouts` rows and protects against duplicate external IDs. Cross-source deduplication is still an area to treat carefully because the same workout can arrive from Strava, Garmin, WHOOP, HealthKit, or manual entry.

General source priorities:

- Recovery, sleep, and daily strain: WHOOP.
- Power, GPS, cadence, laps, and per-second workout streams: Strava/Garmin.
- Manual and HealthKit entries: fallback or user-entered summaries.

## Sport Mapping

Strava sport types are normalized to ASTRAPHE's canonical sport tokens:

| ASTRAPHE sport | Examples |
|---|---|
| `run` | Run, TrailRun, VirtualRun |
| `bike` | Ride, VirtualRide, EBikeRide |
| `row` | Rowing, VirtualRow |
| `swim` | Swim |
| `strength` | WeightTraining, Workout |
| `mobility` | yoga/stretching-style sessions when mapped by backend logic |
| `other` | Unknown or unsupported types |

## Remaining Work

The backend has the core Strava plumbing. Product polish remains around:

- Richer mobile workout detail visualizations.
- Deeper cross-source merge rules for near-duplicate workouts.
- User-facing repair flows for failed stream/lap hydration.
- Segment/best-effort analysis.
- More explicit rate-limit backoff for large historical imports.
