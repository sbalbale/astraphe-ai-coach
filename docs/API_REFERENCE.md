# API Reference

## Base URL

```
Production:  https://api.astrape-coach.app/v1
Development: http://localhost:8000/v1
```

## Authentication

All endpoints require a Supabase JWT in the Authorization header:

```
Authorization: Bearer <supabase_jwt>
```

The API validates the JWT against the Supabase project's public key and extracts `athlete_id` from the claims. Every database query is automatically scoped to the authenticated athlete via RLS.

**Error format** (all errors):
```json
{ "detail": "message string" }
```

---

## Health

### GET `/health`

Liveness check — no auth required.

**Response:**
```json
{ "status": "healthy", "service": "ASTRAPE API" }
```

---

## Athlete

### GET `/athlete/state`

Returns the athlete's current physiological state including computed CTL, ATL, TSB, and readiness score.

**Response:**
```json
{
  "athlete_id": "uuid",
  "display_name": "Marcus Jensen",
  "date": "2026-04-26",
  "ctl": 68.4,
  "atl": 38.1,
  "tsb": 28.2,
  "hrv_rmssd": 78.0,
  "hrv_delta_7d": 6.3,
  "resting_hr": 52,
  "sleep_hours": 7.5,
  "sleep_score": 94,
  "recovery_score": 78,
  "readiness_score": 78,
  "readiness_label": "Optimal",
  "readiness_recommendation": "High HRV and positive TSB — strong window for a quality effort today."
}
```

---

### GET `/athlete/metrics`

Returns computed PMC metrics over a date range.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `start_date` | ISO date | 42 days ago | Range start |
| `end_date` | ISO date | today | Range end |
| `metrics` | comma-sep string | `ctl,atl,tsb` | Metrics to include |

**Response:**
```json
{
  "athlete_id": "uuid",
  "start_date": "2026-03-15",
  "end_date": "2026-04-26",
  "series": [
    {
      "date": "2026-03-15",
      "ctl": 58.2,
      "atl": 62.4,
      "tsb": -4.2,
      "daily_tss": 85.0
    }
  ]
}
```

---

### PATCH `/athlete/profile`

Update athlete physiological anchors.

**Request body** (all fields optional):
```json
{
  "weight_kg": 75.5,
  "ftp_watts": 285,
  "max_hr": 185,
  "threshold_hr": 162,
  "threshold_pace": 4.37
}
```

**Response:** `200 OK` with updated athlete profile.

---

### POST `/athlete/onboard`

Seeds an athlete account with sample training plan data for a fresh onboarding experience. Safe to call multiple times (uses upsert).

**Response:** `{ "status": "success", "message": "Athlete onboarded with sample data" }`

---

## Workouts

### GET `/workouts`

Returns workout history, newest first.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Max results to return |

**Response:** Array of workout objects:
```json
[
  {
    "id": "uuid",
    "source": "garmin",
    "sport": "run",
    "title": "Easy Recovery Run",
    "started_at": "2026-04-26T12:30:00Z",
    "ended_at": "2026-04-26T13:15:00Z",
    "duration_secs": 2700,
    "distance_m": 9200,
    "avg_hr": 132,
    "max_hr": 158,
    "tss": 38.0,
    "if_value": 0.71
  }
]
```

---

### POST `/workouts`

Ingest a new completed workout. TSS computation and CTL/ATL recalculation run as a background task.

**Request body:**
```json
{
  "source": "healthkit",
  "external_id": "HKWorkout-uuid",
  "sport": "run",
  "started_at": "2026-04-26T12:30:00Z",
  "ended_at": "2026-04-26T13:15:00Z",
  "distance_m": 9200.0,
  "avg_hr": 132,
  "max_hr": 158,
  "avg_pace_sec_km": 293
}
```

**Response:**
```json
{ "status": "success", "message": "Workout ingestion and analysis queued." }
```

---

### DELETE `/workouts/{workout_id}`

Delete a workout by UUID. Also removes the corresponding `tss_history` contribution and triggers CTL/ATL recalculation.

**Response:** `200 OK` on success, `404` if not found or not owned by the athlete.

---

## Biometrics

### GET `/biometrics`

Returns daily biometric readings with running HRV and RHR z-scores attached.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 60 | Days to return |
| `before` | ISO date | today | Cursor: return days before this date (exclusive) |
| `start_date` | ISO date | — | Explicit range start (overrides cursor) |
| `end_date` | ISO date | — | Explicit range end |
| `all` | bool | false | Return full history (use with care) |

**Response:**
```json
{
  "hrvData": [78.0, 74.5, 81.2],
  "sleepData": [7.5, 6.8, 8.1],
  "sleepScores": [94, 78, 91],
  "series": [
    {
      "date": "2026-04-26",
      "hrv_rmssd": 78.0,
      "hrv_z": 0.45,
      "resting_hr": 52,
      "rhr_z": -0.3,
      "sleep_duration_min": 450,
      "sleep_score": 94,
      "sleep_deep_pct": 22.0,
      "sleep_rem_pct": 24.0,
      "recovery_score": 78,
      "strain_score": 14.2,
      "spo2_pct": 98.0,
      "periods": []
    }
  ],
  "page": {
    "limit": 60,
    "start_date": "2026-02-25",
    "end_date": "2026-04-26",
    "has_more": false,
    "next_before": null
  }
}
```

---

### POST `/biometrics/daily`

Ingest a daily biometric summary. Recovery score calculation runs as a background task.

**Request body:**
```json
{
  "date": "2026-04-26",
  "source": "whoop",
  "hrv_rmssd": 78.0,
  "resting_hr": 52,
  "sleep_duration_min": 450,
  "sleep_score": 94,
  "sleep_deep_pct": 22.0,
  "sleep_rem_pct": 24.0,
  "skin_temp_deviation": 0.1,
  "spo2_pct": 98.0
}
```

**Response:**
```json
{ "status": "success", "message": "Biometrics recorded and recovery analysis queued", "date": "2026-04-26" }
```

---

## AI Coach

> **Premium required.** All `/coach` endpoints return `403` for `free` and `trial` tier athletes.

### POST `/coach/message`

Send a message to the ASTRAPE AI coach. Streams the response via Server-Sent Events.

**Request body:**
```json
{
  "conversation_id": "uuid-or-null",
  "message": "Should I do a hard session tomorrow?"
}
```

**Response:** `text/event-stream`
```
data: Based on your TSB of +28 and HRV at 78ms

data:  — 9% above your baseline — tomorrow is

data:  a genuine green-light day. I'd target the

data:  VO2max intervals from the plan: 5×4min @95% FTP.

data: [DONE]
```

On `[DONE]` the client should close the stream. The full response is stored in `coach_messages` and a memory embedding is written to `coach_memories`.

---

### GET `/coach/conversations`

List all conversation threads for the authenticated athlete.

**Response:** Array of conversation summaries with `id`, `title`, `created_at`, `updated_at`.

---

### GET `/coach/conversation/{conversation_id}`

Returns full message history for a conversation.

**Response:**
```json
{
  "conversation_id": "uuid",
  "created_at": "2026-04-26T08:00:00Z",
  "messages": [
    { "role": "user", "content": "Should I do a hard session tomorrow?", "created_at": "..." },
    { "role": "assistant", "content": "Based on your TSB...", "created_at": "..." }
  ]
}
```

---

### DELETE `/coach/conversation/{conversation_id}`

Deletes a conversation and all its messages.

---

## Sync & Integrations

### POST `/sync/garmin/webhook`

Webhook receiver for Garmin Connect push notifications.

**Headers:** `X-Garmin-Signature: <hmac-sha256>`

**Response:** `200 OK` (must respond within 5 seconds or Garmin retries)

---

### POST `/sync/whoop/webhook`

Webhook receiver for WHOOP data push events (workout, recovery, sleep).

**Headers:** `X-WHOOP-Signature: <hmac-sha256>`

---

### GET `/sync/oauth/whoop/authorize`

Initiates WHOOP OAuth 2.0 authorization flow. Redirects to WHOOP's authorization page.

**Query params:** `athlete_id`

**Response:** `302 Redirect` to `https://api.prod.whoop.com/oauth/oauth2/auth`

---

### GET `/sync/oauth/whoop/callback`

OAuth callback handler. Exchanges authorization code for access + refresh tokens, then redirects to the mobile app.

**Response:** `302 Redirect` to deep link `astrape://connected?provider=whoop` (or HTML splash page for browser-based flows)

---

### GET `/sync/status`

Returns connection status for all configured integrations.

**Response:**
```json
{
  "integrations": {
    "garmin": { "connected": true, "last_sync": "2026-04-26T10:14:00Z" },
    "whoop": { "connected": false, "last_sync": null },
    "healthkit": { "connected": false, "last_sync": null }
  }
}
```

> Note: `healthkit` reports `connected: false` until a verifiable sync handshake from the mobile client is received. The Garmin `last_sync` is currently a placeholder value; WHOOP's is live from the OAuth token record.

---

### DELETE `/sync/{provider}`

Unlinks a third-party integration by deleting its OAuth tokens. `provider` must be `garmin` or `whoop`.

**Response:**
```json
{ "status": "success", "provider": "whoop", "remaining_providers": [] }
```

---

## Training Plan (Legacy / Mobile UI)

> **Premium required.** Returns `403` for non-premium athletes.

### GET `/plan`

Returns the athlete's training plan for a date range in a mobile-friendly format used by the Plan screen.

**Query parameters:** `start_date`, `end_date` (default: today → today+7d)

**Response:**
```json
{
  "workouts": [
    { "type": "run", "title": "Tempo Run", "date": "Mon", "duration": "55m", "load": 68 }
  ],
  "plan": {
    "12": { "type": "run", "title": "Tempo Run", "duration": "55 min", "tss": 68, "status": "planned", "note": "Z3-Z4 effort" }
  }
}
```

---

## Training Plans (CRUD)

Full CRUD for planned workout sessions. Used by the AI coach to schedule and modify training blocks.

### GET `/training-plans`

Returns planned workouts as Workout objects.

**Query parameters:** `start_date`, `end_date` (ISO dates)

**Response:** Array of workout objects with `id`, `date`, `title`, `sport`, `primary_zone`, `duration_minutes`, `projected_tss`, `description`, `structure`, `completed`.

---

### POST `/training-plans`

Create a planned workout.

**Request body:**
```json
{
  "source": "manual",
  "sport": "run",
  "title": "Threshold Intervals",
  "date": "2026-05-12",
  "duration_minutes": 65,
  "projected_tss": 85,
  "primary_zone": "Threshold",
  "description": "5×4min @95% FTP with 3min recovery jog.",
  "structure": [
    { "label": "Warm-up", "duration_min": 15, "zone": "Z1-Z2" },
    { "label": "Main set", "duration_min": 35, "zone": "Z4-Z5" },
    { "label": "Cool-down", "duration_min": 15, "zone": "Z1" }
  ],
  "completed": false
}
```

**Response:** Created workout object.

---

### PUT `/training-plans/{training_plan_id}`

Replace a planned workout. Sets `status` to `done` if `completed: true`, otherwise `modified`.

**Request body:** Same as POST.

**Response:** Updated workout object.

---

### DELETE `/training-plans`

Delete training plan rows in a date range. Requires at least one of `start_date` or `end_date`.

**Query parameters:** `start_date`, `end_date`

**Response:**
```json
{ "status": "success", "deleted": 5 }
```

---

## AI Analysis

Cached, AI-generated insight strings for specific screens and contexts. All endpoints check the athlete's tier and fall back to a deterministic rule-based summary for `free`/`trial` users if the Gemini call would be gated. Results are cached per `(athlete_id, analysis_type, scope_key)` and reused until the underlying data changes (fingerprinting).

### GET `/analysis/recovery`

One-sentence recovery insight for a given day.

**Query parameters:** `day` (YYYY-MM-DD, default today)

**Response:**
```json
{
  "status": "success",
  "analysis": {
    "content": "Your signals are mixed but workable (recovery 58/100, HRV 74 vs 78, RHR 54 vs 52, TSB -4); keep training controlled and use how you feel to decide intensity.",
    "fingerprint": "sha256-...",
    "cached": true,
    "model": "gemini-flash-lite-latest"
  }
}
```

---

### GET `/analysis/sleep`

One-sentence sleep quality insight for a given day.

**Query parameters:** `day` (YYYY-MM-DD, default today)

**Response:** Same shape as `/analysis/recovery`.

---

### GET `/analysis/strain`

One-sentence daily strain / load insight.

**Query parameters:** `day` (YYYY-MM-DD, default today)

**Response:** Same shape as `/analysis/recovery`.

---

### GET `/analysis/training-load`

Weekly training load insight (CTL/ATL/TSB trend + weekly TSS).

**Query parameters:** `end_day` (YYYY-MM-DD, default today)

**Response:** Same shape as `/analysis/recovery`.

---

### GET `/analysis/dashboard-summary`

Blended dashboard insight combining recovery, sleep, HRV, and training load signals.

**Query parameters:** `day` (YYYY-MM-DD, default today)

**Response:** Same shape as `/analysis/recovery`.

---

### GET `/analysis/workout/{workout_id}`

AI insight for a specific completed workout. Returns workout-level effort classification and next-step recommendation.

> **Premium only** — returns a static fallback for free users.

**Response:** Same shape as `/analysis/recovery`.

---

## Debug

> **Development only.** All debug endpoints return `404` in `APP_ENV != "development"`.

### GET `/debug/connection`

End-to-end connectivity and RLS verification for the currently logged-in user.

**Response:**
```json
{
  "backend_env": "development",
  "backend_supabase_url": "http://localhost:57321",
  "athlete": { "id": "uuid", "user_id": "uuid", "display_name": "...", "created_at": "..." },
  "counts_visible_under_rls": {
    "workouts": 14,
    "biometrics": 21,
    "training_plans": 7
  },
  "notes": [
    "If athlete is null -> your auth user exists but no athletes row is visible under RLS for this JWT.",
    "If counts are 0 but you expect data -> you are likely logged into a different Supabase project/environment."
  ]
}
```

---

## Error Responses

| HTTP Status | Typical Cause |
|---|---|
| 401 | Missing or expired JWT |
| 403 | Premium tier required |
| 404 | Resource not found (or debug endpoint in production) |
| 409 | Duplicate `external_id` on workout ingestion |
| 422 | Request body validation failed (Pydantic) |
| 500 | Unexpected server error |

---

## Rate Limits

Not enforced at the API layer in the current implementation. Cloud Run's concurrency limits and Supabase's connection pool (via PgBouncer) act as implicit throttles.
