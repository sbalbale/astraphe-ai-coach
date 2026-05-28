# Data Models

## Source Of Truth

The authoritative schema history is `supabase/migrations/`. This document describes the current public data model at a high level; it is not a generated schema snapshot.

Generated schema output, when used, lives at `docs/schema/astraphe_public_schema.sql` and can lag behind migrations unless regenerated manually.

## Auth And User Configuration

User identity is Supabase Auth. Most API routes resolve:

```text
Authorization JWT -> auth.users.id -> athletes.user_id -> athletes.id
```

Admin-controlled user settings are read from `auth.users.app_metadata`:

- `tier`
- `gemini_model`
- `gemini_analysis_model`
- `rate_limit_rpm`
- `rate_limit_rph`
- `is_admin`

`user_metadata` is not trusted for authorization. The `athletes.tier` column still exists and defaults to `premium`, but backend authorization/model/rate-limit decisions use app metadata.

## RLS Pattern

Athlete-owned public tables generally use this ownership pattern:

```sql
athlete_id IN (
  SELECT id FROM athletes WHERE user_id = auth.uid()
)
```

The API also scopes every request by resolved athlete ID and uses a per-request Supabase client authenticated with the user's JWT, so RLS remains active.

## Core Tables

### `athletes`

One row per application user. Created from Supabase auth onboarding/trigger flows and updated through profile routes.

Important fields:

- `id`
- `user_id`
- `display_name`
- `date_of_birth`
- `gender`
- `city`
- `country_code`
- `weight_kg`
- `height_cm`
- `max_hr`
- `resting_hr`
- `threshold_hr`
- `threshold_hr_source`
- `threshold_pace`
- `ftp_watts`
- `vo2max_est`
- `sport_focus`
- `weekly_tss_target`
- `timezone_offset_min`
- `measurement_units`
- `training_zones`
- `hr_zone_method`
- `notification_settings`
- `privacy_settings`
- `tier` default `premium`
- timestamps

Allowed `hr_zone_method` values are `lthr`, `hrr`, and `max_hr`.

### `workouts`

Canonical completed workouts, regardless of source.

Important fields:

- `id`
- `athlete_id`
- `source`
- `external_id`
- `sport`
- `title`
- `started_at`
- `ended_at`
- `duration_seconds`
- `distance_m`
- `elevation_gain_m`
- `avg_hr`
- `max_hr`
- `avg_power_w`
- `norm_power_w`
- `avg_pace_sec_km`
- `hr_zone_0_pct` through `hr_zone_5_pct`
- `tss`
- `if_value`
- `strain_score`
- `fit_file_url` — optional URL/path to a **raw Garmin `.fit` artifact** (future direct Garmin ingest). Not the canonical stream store; canonical streams live in Supabase Storage bucket `activity-streams` as gzip JSON (`activity_streams.storage_path`). Parsed FIT data uses the same `time_series` schema as Strava/WHOOP.
- Strava-related detail/source columns from later migrations

Allowed sources include `garmin`, `whoop`, `healthkit`, `manual`, and `strava`.

Allowed sports are:

```text
run, bike, swim, strength, row, mobility, other
```

### `biometrics`

Daily physiological summaries.

Important fields:

- `id`
- `athlete_id`
- `date`
- `source`
- `external_id`
- `hrv_rmssd`
- `hrv_source`
- `resting_hr`
- `sleep_duration_min`
- `sleep_in_bed_min`
- `sleep_score`
- sleep stage percentages/minutes where present
- `sleep_bedtime`
- `sleep_wakeup`
- `skin_temp`
- `spo2_pct`
- `recovery_score`
- `readiness_score`
- `strain_score`

`skin_temp` stores absolute Celsius.

### `sleep_periods`

Per-period sleep records, including naps, linked to an athlete and source.

Used when daily sleep has multiple periods or richer source details.

### `tss_history`

Daily training load ledger and source of current CTL/ATL/TSB values.

Important fields:

- `athlete_id`
- `date`
- `daily_tss`
- `workout_ids`
- `ctl`
- `atl`
- `tsb`

Unique by `(athlete_id, date)`.

### `training_plans`

Planned workouts. Backend API exposes canonical fields such as `date`, `duration_minutes`, and `projected_tss`, while the database uses legacy columns:

| API field | DB column |
|---|---|
| `date` | `planned_date` |
| `duration_minutes` | `duration_min` |
| `projected_tss` | `target_tss` |

Important fields:

- `sport`
- `title`
- `description`
- `duration_min`
- `target_tss`
- `target_zones`
- `primary_zone`
- `structure`
- `goal`
- `context`
- `status`
- `completed_workout_id`
- `generated_by`

`structure` stores structured intervals as JSONB.

## Integrations

### `oauth_tokens`

Stores third-party tokens by athlete/provider.

Providers currently include WHOOP, Garmin-related flows, and Strava. Token access is server-side; clients never receive OAuth tokens.

Important fields:

- `athlete_id`
- `provider`
- `access_token`
- `refresh_token`
- `expires_at`
- `scope`
- provider metadata columns from integration migrations

### `activity_streams`

Stores heavy per-second activity streams separately from `workouts`.

Important fields:

- `workout_id`
- `athlete_id`
- `stream_data` / stream JSON payload fields from migration
- metadata such as resolution/source

### `activity_laps`

Stores lap/split detail for activity detail screens.

Important fields:

- `workout_id`
- `athlete_id`
- `lap_index`
- timing/distance fields
- HR/power/cadence/speed fields
- raw lap payload fields

### `push_tokens`

Stores web and native push tokens/subscriptions.

Important fields:

- `athlete_id`
- `platform`
- `token`
- timestamps

Protected by RLS so athletes manage their own token rows.

## Coach And AI

### `coach_conversations`

Conversation thread metadata:

- `id`
- `athlete_id`
- `title`
- timestamps

### `coach_messages`

Individual user/assistant messages:

- `conversation_id`
- `athlete_id`
- `role`
- `content`
- `image_urls`
- timestamps

### `coach_memories`

Long-term coach memory with pgvector embeddings.

Important fields:

- `athlete_id`
- `content`
- `memory_type`
- `context_date`
- `metadata`
- `embedding vector(3072)`
- timestamps

The current migration creates vector support and RLS. Do not assume an HNSW index exists unless verified against the latest migration state.

### `athlete_analyses`

Cached screen-level AI analysis results.

Important fields:

- `athlete_id`
- `analysis_type`
- `scope_key`
- `fingerprint`
- `content`
- `model`
- timestamps

Used by `/v1/analysis/*` routes to avoid repeated LLM calls when source data has not changed.

## Storage

Coach uploads use the `coach-uploads` bucket and path prefixes based on the authenticated user/conversation. The bucket privacy/RLS state is governed by migrations and Supabase Storage policies; the current frontend upload helper still uses `getPublicUrl()` after upload.

## Pydantic Models

Request/response schemas live in `backend/app/models/` and router-local models. Treat those as the API contract source when they differ from database column names.

Important files:

- `backend/app/models/athlete.py`
- `backend/app/models/workout.py`
- `backend/app/models/biometrics.py`
- `backend/app/routers/coach.py`
- `backend/app/routers/notifications.py`

## Schema Maintenance

When migrations change tables, update this document manually and optionally regenerate `docs/schema/astraphe_public_schema.sql` with `docs/tools/generate_schema.py`.
