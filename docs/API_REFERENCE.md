# API Reference

## Base URL

```text
Production:  https://api.astrapheai.com/v1
Development: http://localhost:8000/v1
```

`GET /health` is mounted outside `/v1`. All other documented routes are prefixed with `/v1`. Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are served only when `APP_ENV != "production"`.

## Authentication

Protected endpoints require a Supabase access token:

```http
Authorization: Bearer <supabase_jwt>
```

The backend verifies the token's signature locally against Supabase Auth's published JWKS (ES256/RS256) and falls back to asking GoTrue (`auth.get_user`) when it can't. It then resolves the matching `athletes.id` and queries through a Supabase client carrying the user's JWT, so RLS stays active. Tokens minted by Supabase's OAuth server for third-party (MCP) clients carry a `client_id` claim and are rejected with `403`. Admin-only routes additionally require `auth.users.app_metadata.is_admin = true`.

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

Post-signup hook kept so older app versions keep working. It no longer seeds any data; it just returns success.

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

Updates profile fields such as physiological anchors, units, notification settings, privacy settings, and onboarding fields. Setting `resting_hr` pins it (`resting_hr_source = 'manual'`); sending `resting_hr_source: "measured"` switches back to the wearable's measured value. Marketing privacy changes are saved first, then synced to Resend if configured.

### `GET /v1/athlete/zones`

Returns calculated HR zones from `max_hr`, `resting_hr`, `threshold_hr`, and `hr_zone_method`.

### `PUT /v1/athlete/zones`

Updates zone anchors and method. Supported methods are `lthr`, `hrr`, and `max_hr` (`max_hr_percent` is accepted as an alias for `max_hr`).

### `DELETE /v1/athlete`

Deletes the authenticated athlete account via the backend account-deletion flow.

## Workouts

### `GET /v1/workouts`

Returns completed workouts, newest first, each with a computed `duration_secs`.

Query parameters:

| Parameter | Default | Notes |
|---|---:|---|
| `limit` | 20 | 1–200 |
| `before` | none | ISO datetime; only workouts that started before it (older pages) |

The first page (no `before`) is cached in Redis.

### `POST /v1/workouts`

Ingests a completed workout and queues processing in the background. Stored `source` values are `garmin`, `whoop`, `healthkit`, `manual`, `strava`, `intervals_icu`, and `hr_detected` (written only by heart-rate auto-detection). Stored sports are `run`, `bike`, `swim`, `strength`, `row`, `mobility`, and `other`.

### `PATCH /v1/workouts/{workout_id}`

Edits a workout (sport, times, duration, distance, power, HR, TSS, title, zone percentages). Keeps `ended_at` and `duration_seconds` consistent when times change, then refreshes load and day strain. Editing an `hr_detected` workout turns it into a manual one.

### `DELETE /v1/workouts/{workout_id}`

Deletes a workout owned by the athlete and recalculates CTL/ATL/TSB and that day's strain. Deleting an `hr_detected` workout records its window in `hr_detection_dismissals` so it isn't detected again.

### `POST /v1/workouts/calculate-tss`

Calculates TSS from a workout payload without saving it. Only cycling is implemented (power-based: needs `norm_power_w` and an FTP from the payload or profile); other types return `400`.

### `GET /v1/workouts/{workout_id}/plan-link`

The planned session this workout completes (if any), planned sessions within two days, and a suggested match.

## Activity Detail

### `GET /v1/activities/{workout_id}/detail`

Returns streams, laps, intervals, and HR zones in one response (single `time_series` read server-side). Prefer this over separate stream/lap/interval/zones calls. Cached in Redis (`detail:{athlete_id}:v{zones_version}:{workout_id}`) when Redis is configured.

### `GET /v1/activities/{workout_id}/streams`

Returns stored per-second stream data for a workout when available. Cached in Redis (`streams:{athlete_id}:{workout_id}`) when Redis is configured.

### `GET /v1/activities/{workout_id}/laps`

Returns stored lap rows for the workout.

### `GET /v1/activities/{workout_id}/intervals`

Returns normalized interval data derived from laps/streams.

### `POST /v1/activities/{workout_id}/hydrate-streams`

Fetches and stores Strava streams for a Strava-backed workout. Limited to 30/hour per athlete.

### `POST /v1/activities/{workout_id}/refetch-strava`

Refetches Strava detail for a workout and refreshes stored stream/lap data. Limited to 20/hour per athlete.

### `GET /v1/activities/{workout_id}/zones`

Returns HR zone distribution for one workout.

## Biometrics

### `GET /v1/biometrics`

Returns daily biometric readings with pagination and derived values. The default first page (no range or cursor parameters) is cached in Redis.

Query parameters:

| Parameter | Default | Notes |
|---|---:|---|
| `limit` | 60 | Number of days (max 3650) |
| `before` | today | Cursor date, exclusive |
| `start_date` | none | Explicit range start |
| `end_date` | none | Explicit range end |
| `all` | `false` | Return full history |

### `POST /v1/biometrics/daily`

Ingests a daily biometric summary. Current payloads use `skin_temp` for absolute Celsius skin temperature;
ingestion derives `skin_temp_deviation_c` (delta from the athlete's own 7-day baseline) from it automatically
unless the source (e.g. Garmin) already supplies a native deviation — see `docs/DATA_MODELS.md`.

### `GET /v1/biometrics/heart-rate`

One local day of all-day heart rate. Query parameter: `date` (defaults to the athlete's local today).

Response fields: `date`, `day_start`, `day_end`, `source`, `interval_sec`, `resting_hr`, `min_hr`, `max_hr`, `avg_hr`, `samples` (`[{t, bpm}]`, empty when the day has no series), `workouts` (recorded ones plus HR-detected ones), `sleep`, and `resting_hr_history` (last 30 days). Cached in Redis for 60 s (today) or 30 min (past days).

## Weight

### `GET /v1/weight`

The last year of weigh-ins (oldest first) plus goal weight, FTP, and preferred units:

```json
{
  "today": "2026-11-09",
  "entries": [{ "id": "uuid", "date": "2026-11-09", "measured_at": "…Z", "weight_kg": 72.4, "body_fat_pct": null, "source": "manual", "time_known": true }],
  "goal_weight_kg": 70.0,
  "ftp_watts": 250,
  "measurement_units": "metric"
}
```

Cached in Redis for 10 minutes.

### `POST /v1/weight`

Logs a weigh-in. Body: `weight_kg` (20–350), optional `date` (not in the future), optional `body_fat_pct` (2–75). Also updates that day's `biometrics.weight_kg`.

### `DELETE /v1/weight/{weigh_in_id}`

Soft-deletes a weigh-in (`deleted_at`); a re-sync won't bring it back.

### `POST /v1/weight/{weigh_in_id}/restore`

Undoes a delete.

### `PUT /v1/weight/goal`

Sets or clears `athletes.goal_weight_kg`. Body: `{ "goal_weight_kg": 70.0 }` (or `null` to clear).

## AI Coach

Coach routes require premium access (tier `premium` or an active `trial`), otherwise `403`. Tier, model override, admin flag, and AI rate-limit overrides are read from `auth.users.app_metadata`, not user-editable metadata. Routes that call a model (`upload-document`, `initialize`, `message`, `message/async`, `stream`) also enforce the per-athlete AI rate limits below.

### `GET /v1/coach/conversations`

Lists conversations, including coach-started ones (`started_by`, `trigger`, `context`, `unread`).

### `POST /v1/coach/conversations`

Creates a conversation. Body: `{ "title": "optional title" }`.

### `POST /v1/coach/conversations/{conversation_id}/read`

Clears the unread flag on a coach-started thread.

### `GET /v1/coach/conversations/{conversation_id}/messages`

Returns ordered messages for a conversation.

### `GET /v1/coach/conversations/{conversation_id}/progress`

Live steps (`started`, `context_ready`, `thinking`, `tool`, `done`) for a reply being generated by `POST /message/async`. `visible=true` marks the chat as on screen so the reply isn't also pushed. Entries expire after 10 minutes.

### `DELETE /v1/coach/conversations/{conversation_id}`

Deletes a conversation and its messages.

### `GET /v1/coach/memories`

Lists the athlete's coach memories. Query parameters: `memory_type`, `limit` (default 50).

### `PATCH /v1/coach/memories/{memory_id}`

Edits `content`, `memory_type`, `entity_key`, or `event_date`.

### `DELETE /v1/coach/memories/{memory_id}`

Deletes one memory.

### `POST /v1/coach/upload-document`

Parses an uploaded PDF, Word (.docx), CSV, or Excel file (multipart form data) and returns the extracted text. The client sends it back with the next message as `documents: [{name, content}]`.

### `POST /v1/coach/initialize`

Called when the chat mounts. Returns a proactive warning when biometrics/load anomalies are severe, otherwise a short greeting, plus the athlete's top memories for suggestions.

### `POST /v1/coach/message`

Returns a complete JSON coach reply.

```json
{
  "message": "How is my fitness trending?",
  "recent_tss": 64,
  "conversation_id": "uuid-or-null",
  "image_urls": [],
  "documents": [{ "name": "plan.pdf", "content": "…" }],
  "timezone_offset_min": -300
}
```

`message` is limited to 8000 characters.

Response:

```json
{
  "status": "success",
  "conversation_id": "uuid",
  "reply": "Athlete-facing text",
  "sources": []
}
```

When the shared model quota is exhausted the route returns `429` with a retry hint.

### `POST /v1/coach/message/async`

Same body as `/message`. Saves the user's message and returns `{ "status": "pending", "conversation_id": "…" }` immediately; the reply is generated in the background, saved to `coach_messages`, and pushed if the chat isn't open. Poll `/progress` and `/messages` for it.

### `POST /v1/coach/stream`

Streams the same coach flow over Server-Sent Events.

## Sync And Integrations

### `POST /v1/sync/garmin/connect`

Connects Garmin with the athlete's Garmin username and password (via the community `garminconnect` library); only the resulting session is stored, never the password. Body: `username`, `password`, optional `days` (default 90). Returns `{ "mfa_required": true, "state_token": "…" }` when the account uses MFA. Limited to 5/hour.

### `POST /v1/sync/garmin/connect/mfa`

Completes an MFA login. Body: `state_token`, `mfa_code`, optional `days`. The pending login is shared through Redis, so it can complete on either API replica. Limited to 10/hour.

### `POST /v1/sync/garmin/backfill`

Backfills Garmin data. Query parameter: `days` (default 90, max 365).

### `POST /v1/sync/garmin/webhook`

Legacy Garmin push receiver. Returns `404` unless `GARMIN_WEBHOOK_SECRET` is set, then requires a valid `X-Garmin-Signature`. Garmin sync is normally poll-only (a background loop every `GARMIN_SYNC_POLL_HOURS`, or `GARMIN_SYNC_POLL_MINUTES` when set).

### `POST /v1/sync/whoop/webhook`

WHOOP webhook receiver. Validates WHOOP HMAC signatures unless development skip mode is explicitly enabled.

### `GET /v1/sync/strava/webhook`

Strava subscription verification endpoint. Echoes the `hub.challenge` after checking `hub.verify_token`.

### `POST /v1/sync/strava/webhook`

Strava event webhook. Verifies owner mapping and queues activity ingestion/backfill work for supported create/update/delete events.

### `GET /v1/sync/oauth/whoop/authorize`

Starts WHOOP OAuth. Optional `web_return` controls browser return behavior; `json_url=true` returns `{ "url": … }` instead of redirecting.

### `GET /v1/sync/oauth/whoop/callback`

Completes WHOOP OAuth, stores tokens, and redirects to the mobile/web return path.

### `GET /v1/sync/oauth/strava/authorize`

Starts Strava OAuth.

### `GET /v1/sync/oauth/strava/callback`

Completes Strava OAuth, stores tokens and athlete mapping, and kicks off recent activity import.

### `GET /v1/sync/status`

Returns connection state for Garmin, WHOOP, Strava, Intervals.icu, and HealthKit (HealthKit always reports disconnected for now).

### `DELETE /v1/sync/{provider}`

Unlinks `garmin`, `whoop`, `strava`, or `intervals_icu`.

### `POST /v1/sync/refresh-strain`

Recalculates strain scores for the authenticated athlete. Limited to 10/hour.

### `POST /v1/sync/reprocess-metrics`

By default runs a fast strain refresh. `full=true` rebuilds all workouts, biometrics, and PMC (slow). Limited to 6/hour.

### `POST /v1/sync/whoop/backfill-biometrics`

Backfills WHOOP sleep and recovery only. Query parameter: `days` (default 90, max 365).

### `POST /v1/sync/whoop/backfill`

Backfills WHOOP workouts/recovery data. Query parameter: `days` (default 90, max 365).

### `POST /v1/sync/strava/backfill`

Backfills Strava activities. Query parameter: `days` (default 90).

### `POST /v1/sync/intervals-icu/connect`

Stores an Intervals.icu athlete ID and API key server-side, verifies access, and queues a workouts/wellness/stream backfill. Body fields: `intervals_athlete_id`, `api_key`, optional `days` (default 90).

### `POST /v1/sync/intervals-icu/backfill`

Backfills Intervals.icu workout summaries, available activity streams, HR anchors/zones, and wellness data. Query parameter: `days` (default 90, max 365). Response includes `workouts`, `streams`, `biometrics`, and `days` counts.

Provider backfills (Garmin, WHOOP, Strava, Intervals.icu) are each limited to 3/hour per athlete.

## Training Plan

### `GET /v1/plan`

Legacy weekly plan projection. Query parameters: `start_date`, `end_date` (default: local today to +7 days). Requires premium access.

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

### `GET /v1/training-plans/{training_plan_id}/candidates`

Recorded workouts within two days of the session, best fit first, plus a one-tap suggestion.

### `POST /v1/training-plans/{training_plan_id}/link`

Links a recorded workout (`workout_id`, optional `move`) to the session and marks it done. `409` if that workout already completes another session.

### `DELETE /v1/training-plans/{training_plan_id}/link`

Unlinks. `dismiss` (default `true`) stops auto-matching that workout to the session; `done=true` keeps the session marked done (used by undo).

### `POST /v1/training-plans/{training_plan_id}/dismiss`

"Not this one": stops suggesting (and auto-matching) `workout_id` for the session.

## Analysis

Screen-level AI insights are cached in `athlete_analyses` by `(athlete_id, analysis_type, scope_key)` and data fingerprint. Accounts with premium access (premium or active trial) get the configured analysis model; free accounts get deterministic fallback summaries (`model: "fallback"`). Regeneration is guarded by a Redis lock so two API replicas don't run the same generation.

Routes:

- `GET /v1/analysis/recovery?day=YYYY-MM-DD`
- `GET /v1/analysis/sleep?day=YYYY-MM-DD`
- `GET /v1/analysis/strain?day=YYYY-MM-DD`
- `GET /v1/analysis/training-load?end_day=YYYY-MM-DD`
- `GET /v1/analysis/dashboard-summary?day=YYYY-MM-DD`
- `GET /v1/analysis/workout/{workout_id}`
- `GET /v1/analysis/time-in-zones?window_start=YYYY-MM-DD&window_end=YYYY-MM-DD&sport=all`

## Notifications

### `POST /v1/notifications/token`

Registers a push token or web-push subscription.

```json
{ "token": "<fcm-token-or-subscription-json>", "platform": "ios" }
```

`platform` may be `ios`, `android`, or `web`.

### `DELETE /v1/notifications/token`

Unregisters a push token/subscription. Same body as `POST`.

### `POST /v1/notifications/test`

Sends a test push to the athlete's devices (at most one per 30 s). Returns `{ "status": "sent" | "no_devices", "delivered_to": n }`.

### `GET /v1/notifications/devices`

`{ "count": n, "platforms": [...] }` for the athlete's registered push tokens.

## Messaging

### `POST /v1/messaging/photon/inbound`

Called by `photon-bridge` for each inbound iMessage text (`message_id`, `sender`, `text`). Authenticated with the shared `X-Photon-Bridge-Token` header, not a user JWT. Returns `{ "status": "accepted" }` and runs the coach in the background; the reply goes back through the bridge. See [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md).

## Admin

Admin routes require `app_metadata.is_admin`. To make the first admin, set the flag in the database:

```sql
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"is_admin": true}'
WHERE email = 'your-admin@email.com';
```

- `GET /v1/admin/users` (`page`, `per_page` up to 100)
- `GET /v1/admin/users/{user_id}`
- `PATCH /v1/admin/users/{user_id}`
- `DELETE /v1/admin/users/{user_id}/config/{field}`
- `POST /v1/admin/coach-memories/merge-duplicates` (one-off maintenance; dry run by default)

`PATCH` updates Supabase Auth app metadata fields `tier`, `gemini_model`, `gemini_analysis_model`, `rate_limit_rpm`, `rate_limit_rph`, and `is_admin`. `DELETE …/config/{field}` clears `gemini_model`, `gemini_analysis_model`, `rate_limit_rpm`, or `rate_limit_rph`.

## Debug

Debug routes are registered only when `APP_ENV != "production"`.

### `GET /v1/debug/connection`

Checks authenticated user, resolved athlete row, and RLS-visible table counts.

## Rate Limits

The API enforces a global per-IP sliding-window limit on all routes except `/health` and the provider `/v1/sync/*/webhook` receivers (`IP_RATE_LIMIT_RPM`, default 100/min). The client IP comes from `CF-Connecting-IP`, else the right-most `X-Forwarded-For` hop.

AI routes also enforce per-athlete minute/hour/day limits. Minute and hour limits come from `app_metadata.rate_limit_rpm` / `rate_limit_rph` overrides or the tier defaults in `backend/app/dependencies.py` (`TIER_DEFAULTS`):

| Tier | Requests/min | Requests/hour | Requests/day |
|---|---:|---:|---:|
| `free` | 5 | 20 | 40 |
| `trial` | 6 | 60 | 150 |
| `premium` | 10 | 150 | 400 |

A `rate_limit_rph` override above the daily default also lifts the daily cap. Expensive non-AI actions (backfills, reprocessing, Garmin login) have their own per-athlete hourly limits, noted on each route. Separately, all replicas share one Gemini free-tier request budget per model (`services/gemini_quota.py`; a no-op when `GEMINI_FREE_TIER=false`), and coach plan imports are capped at `PLAN_IMPORTS_PER_DAY` (default 5) per athlete per day.

Redis is used when `REDIS_URL` is configured; otherwise these limits fall back to per-process memory.
