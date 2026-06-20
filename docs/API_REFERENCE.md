# API Reference

## Base URL

```text
Production:  https://api.astrapheai.com/v1
Development: http://localhost:8000/v1
```

`GET /health` is mounted outside `/v1`. All other documented routes are prefixed with `/v1`.

## Authentication

Protected endpoints require a Supabase access token:

```http
Authorization: Bearer <supabase_jwt>
```

The backend validates the token with Supabase Auth, resolves the matching `athletes.id`, and uses a per-request Supabase client with the user's JWT so RLS remains active. Admin-only routes additionally require `auth.users.app_metadata.is_admin = true`.

Errors use FastAPI's normal shape:

```json
{ "detail": "message string" }
```

## Health

### `GET /health`

No auth. Returns API, Redis, and Supabase status.

```json
{
  "status": "healthy",
  "service": "ASTRAPHE API",
  "version": "1.0.0",
  "redis": "connected",
  "supabase": "connected"
}
```

`status` becomes `degraded` when Supabase is unavailable.

## Athlete

### `POST /v1/athlete/onboard`

Seeds sample athlete data for first-run onboarding. Safe to call more than once.

### `GET /v1/athlete/state`

Returns current load, recovery, readiness, profile anchors, and streak/profile completion data for the authenticated athlete.

### `GET /v1/athlete/metrics`

Returns PMC time series.

Query parameters:

| Parameter | Default | Notes |
|---|---:|---|
| `start_date` | 42 days ago | ISO date |
| `end_date` | today | ISO date |
| `metrics` | `ctl,atl,tsb` | Comma-separated metric list |

### `GET /v1/athlete/profile`

Returns profile fields, settings JSON, integration-facing metadata, and HR zone settings.

### `PATCH /v1/athlete/profile`

Updates profile fields such as physiological anchors, units, notification settings, privacy settings, and onboarding fields. Marketing privacy changes are saved first, then synced to Resend if configured.

### `GET /v1/athlete/zones`

Returns calculated HR zones from `max_hr`, `resting_hr`, `threshold_hr`, and `hr_zone_method`.

### `PUT /v1/athlete/zones`

Updates zone anchors and method. Supported methods are `lthr`, `hrr`, and `max_hr`.

### `DELETE /v1/athlete`

Deletes the authenticated athlete account via the backend account-deletion flow.

## Workouts

### `GET /v1/workouts`

Returns completed workouts, newest first.

Query parameters:

| Parameter | Default | Notes |
|---|---:|---|
| `limit` | 20 | Maximum number of rows |

### `POST /v1/workouts`

Ingests a completed workout and queues downstream processing. Accepted `source` values include `manual`, `healthkit`, `garmin`, `whoop`, and `strava`. Accepted sports are `run`, `bike`, `swim`, `strength`, `row`, `mobility`, and `other`.

### `DELETE /v1/workouts/{workout_id}`

Deletes a workout owned by the athlete and recalculates downstream load data.

### `POST /v1/workouts/calculate-tss`

Calculates TSS from a workout payload without saving a new completed workout.

## Activity Detail

### `GET /v1/activities/{workout_id}/detail`

Returns streams, laps, intervals, and HR zones in one response (single `time_series` read server-side). Prefer this over separate stream/lap/interval/zones calls. Cached in Redis (`detail:{athlete_id}:{workout_id}`) when Redis is configured.

### `GET /v1/activities/{workout_id}/streams`

Returns stored per-second stream data for a workout when available. Strava stream payloads are cached in Redis when Redis is configured.

### `GET /v1/activities/{workout_id}/laps`

Returns stored lap rows for the workout.

### `GET /v1/activities/{workout_id}/intervals`

Returns normalized interval data derived from laps/streams.

### `POST /v1/activities/{workout_id}/hydrate-streams`

Fetches and stores Strava streams for a Strava-backed workout.

### `POST /v1/activities/{workout_id}/refetch-strava`

Refetches Strava detail for a workout and refreshes stored stream/lap data.

### `GET /v1/activities/{workout_id}/zones`

Returns HR zone distribution for one workout.

## Biometrics

### `GET /v1/biometrics`

Returns daily biometric readings with pagination and derived values.

Query parameters:

| Parameter | Default | Notes |
|---|---:|---|
| `limit` | 60 | Number of days |
| `before` | today | Cursor date, exclusive |
| `start_date` | none | Explicit range start |
| `end_date` | none | Explicit range end |
| `all` | `false` | Return full history |

### `POST /v1/biometrics/daily`

Ingests a daily biometric summary. Current payloads use `skin_temp` for absolute Celsius skin temperature.

## AI Coach

All coach routes require a user config from `auth.users.app_metadata`. Tier, model override, admin flag, and AI rate-limit overrides are read from app metadata, not user-editable metadata.

### `GET /v1/coach/conversations`

Lists conversations.

### `POST /v1/coach/conversations`

Creates a conversation. Body: `{ "title": "optional title" }`.

### `GET /v1/coach/conversations/{conversation_id}/messages`

Returns ordered messages for a conversation.

### `DELETE /v1/coach/conversations/{conversation_id}`

Deletes a conversation and its messages.

### `POST /v1/coach/upload-document`

Uploads a coach document attachment. Requires multipart form data.

### `POST /v1/coach/initialize`

Warms coach context for the authenticated athlete.

### `POST /v1/coach/message`

Returns a complete JSON coach reply.

```json
{
  "message": "How is my fitness trending?",
  "recent_tss": 64,
  "conversation_id": "uuid-or-null",
  "image_urls": []
}
```

Response:

```json
{
  "status": "success",
  "conversation_id": "uuid",
  "reply": "Athlete-facing text",
  "sources": []
}
```

### `POST /v1/coach/stream`

Streams the same coach flow over Server-Sent Events. Use this route when a streaming UI is needed.

## Sync And Integrations

### `POST /v1/sync/garmin/webhook`

Garmin webhook receiver. Uses the configured Garmin webhook secret when available.

### `POST /v1/sync/whoop/webhook`

WHOOP webhook receiver. Validates WHOOP HMAC signatures unless development skip mode is explicitly enabled.

### `GET /v1/sync/strava/webhook`

Strava subscription verification endpoint. Echoes the `hub.challenge` after checking `hub.verify_token`.

### `POST /v1/sync/strava/webhook`

Strava event webhook. Verifies owner mapping and queues activity ingestion/backfill work for supported create/update/delete events.

### `GET /v1/sync/oauth/whoop/authorize`

Starts WHOOP OAuth. Optional `web_return` controls browser return behavior.

### `GET /v1/sync/oauth/whoop/callback`

Completes WHOOP OAuth, stores tokens, and redirects to the mobile/web return path.

### `GET /v1/sync/oauth/strava/authorize`

Starts Strava OAuth.

### `GET /v1/sync/oauth/strava/callback`

Completes Strava OAuth, stores tokens and athlete mapping, and kicks off recent activity import.

### `GET /v1/sync/status`

Returns connection state for Garmin, WHOOP, Strava, Intervals.icu, and HealthKit.

### `DELETE /v1/sync/{provider}`

Unlinks `garmin`, `whoop`, `strava`, or `intervals_icu`.

### `POST /v1/sync/refresh-strain`

Recalculates strain scores for the authenticated athlete.

### `POST /v1/sync/reprocess-metrics`

Reprocesses load metrics. `full=true` performs a broader rebuild.

### `POST /v1/sync/whoop/backfill-biometrics`

Backfills WHOOP biometrics. Query parameter: `days` (default 90).

### `POST /v1/sync/whoop/backfill`

Backfills WHOOP workouts/recovery data. Query parameter: `days` (default 90).

### `POST /v1/sync/strava/backfill`

Backfills Strava activities. Query parameter: `days` (default 90).

### `POST /v1/sync/intervals-icu/connect`

Stores an Intervals.icu athlete ID and API key server-side, verifies access, and queues a workouts/wellness/stream backfill. Body fields: `intervals_athlete_id`, `api_key`, optional `days` (default 90).

### `POST /v1/sync/intervals-icu/backfill`

Backfills Intervals.icu workout summaries, available activity streams, and wellness data. Query parameter: `days` (default 90). Response includes `workouts`, `streams`, `biometrics`, and `days` counts.

## Training Plan

### `GET /v1/plan`

Legacy/mobile-friendly weekly plan projection.

### `GET /v1/training-plans`

Returns planned workouts. Query parameters: `start_date`, `end_date`.

### `POST /v1/training-plans`

Creates a planned workout.

### `PUT /v1/training-plans/{training_plan_id}`

Replaces a planned workout.

### `DELETE /v1/training-plans/{training_plan_id}`

Deletes one planned workout.

### `DELETE /v1/training-plans`

Deletes planned workouts in a date range. Requires `start_date`, `end_date`, or both.

## Analysis

Screen-level AI insights are cached in `athlete_analyses` by `(athlete_id, analysis_type, scope_key)` and data fingerprint. Premium users can use the configured Gemini analysis model; free/trial users receive deterministic fallback summaries where implemented.

Routes:

- `GET /v1/analysis/recovery?day=YYYY-MM-DD`
- `GET /v1/analysis/sleep?day=YYYY-MM-DD`
- `GET /v1/analysis/strain?day=YYYY-MM-DD`
- `GET /v1/analysis/training-load?end_day=YYYY-MM-DD`
- `GET /v1/analysis/dashboard-summary?day=YYYY-MM-DD`
- `GET /v1/analysis/workout/{workout_id}`
- `GET /v1/analysis/time-in-zones?window_start=YYYY-MM-DD&window_end=YYYY-MM-DD`

## Notifications

### `POST /v1/notifications/token`

Registers a push token or web-push subscription.

```json
{ "token": "<fcm-token-or-subscription-json>", "platform": "ios" }
```

`platform` may be `ios`, `android`, or `web`.

### `DELETE /v1/notifications/token`

Unregisters a push token/subscription.

### `POST /v1/notifications/test`

Sends a test push notification. Disabled in production.

## Admin

Admin routes require `app_metadata.is_admin`.

- `GET /v1/admin/users`
- `GET /v1/admin/users/{user_id}`
- `PATCH /v1/admin/users/{user_id}`
- `DELETE /v1/admin/users/{user_id}/config/{field}`

Admin config writes update Supabase Auth app metadata fields such as `tier`, `gemini_model`, `gemini_analysis_model`, `rate_limit_rpm`, and `rate_limit_rph`.

## Debug

Debug routes are registered only when `APP_ENV != "production"`.

### `GET /v1/debug/connection`

Checks authenticated user, resolved athlete row, and RLS-visible table counts.

## Rate Limits

The API enforces a global per-IP sliding-window limit on all routes except `/health` (`IP_RATE_LIMIT_RPM`, default 100/min). AI routes also enforce per-athlete minute/hour limits from `auth.users.app_metadata` overrides or tier defaults:

| Tier | Requests/min | Requests/hour |
|---|---:|---:|
| `free` | 5 | 20 |
| `trial` | 15 | 75 |
| `premium` | 40 | 200 |

Redis is used when `REDIS_URL` is configured; otherwise the limiter falls back to per-process memory.
