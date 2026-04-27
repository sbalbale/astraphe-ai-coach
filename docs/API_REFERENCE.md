# API Reference

## Base URL

```
Production:  https://api.apex-coach.app/v1
Development: http://localhost:8000/v1
```

## Authentication

All endpoints (except `/auth/*`) require a Supabase JWT in the Authorization header:

```
Authorization: Bearer <supabase_jwt>
```

The API validates the JWT against the Supabase project's public key and extracts `athlete_id` from the token claims. Every database query is automatically scoped to the authenticated athlete.

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

Returns computed metrics over a date range.

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

**Request body:**
```json
{
  "weight_kg": 75.5,
  "ftp_watts": 285,
  "max_hr": 185,
  "threshold_hr": 162,
  "threshold_pace": 4.37
}
```

All fields are optional. Only provided fields are updated. After a physiological anchor update (FTP, max HR), all historical TSS values are recomputed asynchronously via a Cloud Tasks job.

**Response:** `200 OK` with updated athlete profile.

---

## Workouts

### GET `/workouts`

Returns paginated workout history.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Results per page (max 100) |
| `offset` | int | 0 | Pagination offset |
| `sport` | string | all | Filter by sport |
| `start_date` | ISO date | 30 days ago | Date range start |
| `end_date` | ISO date | today | Date range end |

**Response:**
```json
{
  "total": 87,
  "limit": 20,
  "offset": 0,
  "workouts": [
    {
      "id": "uuid",
      "source": "garmin",
      "sport": "run",
      "title": "Easy Recovery Run",
      "started_at": "2026-04-26T12:30:00Z",
      "duration_secs": 2700,
      "distance_m": 9200,
      "avg_hr": 132,
      "tss": 38.0,
      "if_value": 0.71
    }
  ]
}
```

---

### POST `/workouts`

Ingest a new workout. Used by the HealthKit background runner and manual entry.

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
{
  "id": "uuid",
  "tss": 38.2,
  "if_value": 0.71,
  "message": "Workout ingested. CTL updated to 68.4."
}
```

**Side effects:**
- TSS computed and stored in `tss_history`
- CTL, ATL, TSB recomputed for the athlete
- Supabase Realtime event emitted (client re-renders)

---

### GET `/workouts/{workout_id}`

Returns full detail for a single workout including zone breakdown.

**Response:**
```json
{
  "id": "uuid",
  "sport": "run",
  "title": "Threshold Intervals",
  "started_at": "2026-04-25T09:00:00Z",
  "duration_secs": 5400,
  "distance_m": 15200,
  "avg_hr": 158,
  "max_hr": 176,
  "tss": 95.4,
  "zone_distribution": {
    "1": {"minutes": 12, "pct": 13},
    "2": {"minutes": 18, "pct": 20},
    "3": {"minutes": 22, "pct": 24},
    "4": {"minutes": 28, "pct": 31},
    "5": {"minutes": 10, "pct": 11}
  },
  "pace_series": [5.2, 5.4, 5.3, 5.6, 5.8]
}
```

---

## Biometrics

### GET `/biometrics`

Returns daily biometric readings over a date range.

**Query parameters:** `start_date`, `end_date` (ISO dates)

**Response:**
```json
{
  "series": [
    {
      "date": "2026-04-26",
      "hrv_rmssd": 78.0,
      "resting_hr": 52,
      "sleep_duration_min": 450,
      "sleep_score": 94,
      "sleep_deep_pct": 22.0,
      "sleep_rem_pct": 24.0,
      "recovery_score": 78,
      "spo2_pct": 98.0
    }
  ]
}
```

---

### POST `/biometrics/daily`

Ingest a daily biometric summary (called by HealthKit/WHOOP sync).

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

---

## AI Coach

### POST `/coach/message`

Send a message to the APEX AI coach. Streams the response via Server-Sent Events.

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

**On `[DONE]`:** The client should stop reading the stream. The full response is simultaneously stored in `coach_memories` server-side.

---

### GET `/coach/conversation/{conversation_id}`

Returns the message history for a conversation.

**Response:**
```json
{
  "conversation_id": "uuid",
  "created_at": "2026-04-26T08:00:00Z",
  "messages": [
    {
      "role": "assistant",
      "content": "Hey Marcus! Your CTL hit 68 — a new high...",
      "created_at": "2026-04-26T08:00:00Z"
    },
    {
      "role": "user",
      "content": "What do you recommend for this week?",
      "created_at": "2026-04-26T08:01:00Z"
    }
  ]
}
```

---

## Sync / Integrations

### POST `/sync/garmin/webhook`

Webhook receiver for Garmin Connect push notifications. Garmin posts here when a workout syncs from the device.

**Headers required by Garmin:**
```
X-Garmin-Signature: <hmac-sha256>
```

**Request body:** Garmin Activity Summary payload (see Garmin API docs).

**Response:** `200 OK` (must respond within 5 seconds or Garmin retries)

---

### POST `/sync/whoop/webhook`

Webhook receiver for WHOOP data push events (workout, recovery, sleep).

**Headers:**
```
X-WHOOP-Signature: <hmac-sha256>
```

---

### GET `/sync/oauth/garmin/authorize`

Initiates the Garmin OAuth 2.0 authorization flow. Redirects to Garmin's authorization page.

**Response:** `302 Redirect` to `https://connect.garmin.com/oauthConfirm`

---

### GET `/sync/oauth/garmin/callback`

OAuth callback handler. Exchanges the authorization code for access + refresh tokens.

**Query params:** `code`, `state`

**Response:** `302 Redirect` to the mobile app deep link `apex://connected?provider=garmin`

---

### GET `/sync/oauth/whoop/authorize`
### GET `/sync/oauth/whoop/callback`

Identical pattern to Garmin OAuth flow above.

---

### GET `/sync/status`

Returns connection status for all configured integrations.

**Response:**
```json
{
  "integrations": {
    "garmin": {
      "connected": true,
      "last_sync": "2026-04-26T10:14:00Z",
      "token_expires": "2026-04-26T12:14:00Z"
    },
    "whoop": {
      "connected": false,
      "last_sync": null
    },
    "healthkit": {
      "connected": true,
      "last_sync": "2026-04-26T06:12:00Z",
      "background_refresh": true
    }
  }
}
```

---

## Training Plan

### GET `/plan`

Returns the athlete's training plan for a date range.

**Query params:** `start_date`, `end_date`

**Response:**
```json
{
  "plan": [
    {
      "id": "uuid",
      "planned_date": "2026-04-27",
      "sport": "run",
      "title": "VO2max Intervals",
      "description": "5×4min @95% FTP with 3min recovery. Warm up 15min, cool down 10min.",
      "duration_min": 65,
      "target_tss": 85,
      "target_zones": {"Z1": 25, "Z2": 0, "Z3": 0, "Z4": 16, "Z5": 24},
      "status": "planned",
      "generated_by": "apex_ai"
    }
  ]
}
```

---

## Error Responses

All errors follow a consistent structure:

```json
{
  "error": {
    "code": "ATHLETE_NOT_FOUND",
    "message": "No athlete record found for the authenticated user.",
    "details": null
  }
}
```

**Common error codes:**

| Code | HTTP Status | Description |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid JWT |
| `ATHLETE_NOT_FOUND` | 404 | No athlete profile for this user |
| `WORKOUT_DUPLICATE` | 409 | Workout with this external_id already exists |
| `INVALID_PAYLOAD` | 422 | Request body validation failed |
| `COMPUTATION_ERROR` | 500 | TSS/CTL calculation failed |
| `AI_UNAVAILABLE` | 503 | Gemini API unreachable |

---

## Rate Limits

| Endpoint Group | Limit |
|---|---|
| `/coach/message` | 60 requests / hour |
| `/workouts POST` | 200 requests / hour |
| `/sync/*/webhook` | 500 requests / hour |
| All other GET endpoints | 600 requests / hour |

Rate limit headers are included on all responses:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1745678400
```
