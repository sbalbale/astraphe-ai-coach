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

All 14 public tables have RLS enabled. Athlete-owned tables generally use this ownership pattern:

```sql
athlete_id IN (
  SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())
)
```

Two details matter if you're writing a new policy:

- `auth.uid()` is wrapped in `(SELECT ...)` deliberately — this caches it once per statement (Postgres "initplan") instead of re-evaluating per row. `20260526233437_rls_policy_performance_fixes.sql` and `20260527014001_fix_rls_initplan_and_duplicate_indexes.sql` rewrote every policy to this form after the unwrapped version caused per-row re-evaluation at scale. Don't reintroduce the bare form.
- Every policy is scoped `TO authenticated` (never `PUBLIC`) and pairs a `USING` clause with a matching `WITH CHECK` clause.

This pattern covers `activity_streams` and `activity_laps` too — their original scalar-subquery policies (`athlete_id = (SELECT id FROM athletes ...)`) would error against a user with multiple athlete rows; `20260526233437` rewrote them to the `IN (...)` form.

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
- `threshold_pace` — `TEXT` holding `"mm:ss"` (migrated from `NUMERIC` by `20260428000003_profile_pace_units.sql`; not a plain number)
- `ftp_watts`
- `vo2max_est`
- `sport_focus`
- `weekly_tss_target`
- `timezone_offset_min`
- `measurement_units`
- `time_format` — `'12h'` or `'24h'`, default `'12h'`
- `hrv_baseline`, `rhr_baseline` — rolling baselines used for readiness scoring
- `hr_zone_method`
- `zone_method` — **generated column** (`GENERATED ALWAYS ... STORED`), derived from `threshold_hr`/`threshold_hr_source`/`max_hr`/`resting_hr`; cannot be written directly
- `lthr` — **generated column**, mirrors `threshold_hr`; cannot be written directly
- `strava_athlete_id` — unique, nullable
- `notification_settings`
- `privacy_settings`
- `tier` default `premium`
- `created_at` only — no `updated_at` on this table

Allowed `hr_zone_method` values are `lthr`, `hrr`, and `max_hr`. There is no `athletes.training_zones` column — zone data is derived (`zone_method`/`lthr`) or lives on `training_plans.target_zones`.

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
- `fit_file_url` — optional URL/path to a **raw Garmin `.fit` artifact** (future direct Garmin ingest). Not the canonical stream store; canonical streams live in Supabase Storage bucket `activity-streams` as gzip JSON (`activity_streams.storage_path`). Parsed FIT/Intervals.icu/Strava data uses the same `time_series` schema.
- `garmin_activity_id` — unique, nullable (`20260805150000_garmin_activity_id_and_calories.sql`)
- `calories`
- Integration detail/source columns from later migrations, including Strava IDs and source merge metadata.

Allowed sources include `garmin`, `whoop`, `healthkit`, `manual`, `strava`, and `intervals_icu`.

Allowed sports are:

```text
run, bike, swim, strength, row, mobility, other
```

### `biometrics`

Daily physiological summaries.

Important fields:

There is no `biometrics.source` or `biometrics.external_id` column — those exist on `workouts` and `sleep_periods`, not here. Per-field provenance on this table is tracked via `metric_sources` instead (see below).

- `id`
- `athlete_id`
- `date`
- `hrv_rmssd`
- `hrv_source`
- `resting_hr`
- `sleep_duration_min`
- `sleep_in_bed_min`
- `sleep_score`, `source_sleep_score` — `sleep_score` is Astraphe's normalized value; `source_sleep_score` is the provider's original, unmodified score (`20260429000000_unify_score_names.sql`). Same pairing for recovery below.
- `recovery_score`, `source_recovery_score`
- sleep stage percentages/minutes where present
- `sleep_bedtime`
- `sleep_wakeup`
- `skin_temp`
- `spo2_pct`
- `readiness_score`
- `strain_score`
- `day_strain`
- `sleep_need_min`, `sleep_debt_min`
- `weight_kg`, `height_cm`
- `metric_sources` — JSONB per-field provenance used for quality-ranked biometrics merges

`skin_temp` stores absolute Celsius (renamed from `skin_temp_deviation` by `20260521130000_rename_skin_temp_column.sql`).
Intervals.icu wellness rows may use `id` as the local wellness date; ingestion maps that to `biometrics.date` (there is no column that stores the original Intervals.icu id). If Intervals.icu supplies sleep duration without sleep-stage percentages, ingestion stores the duration, leaves stage percentages `NULL`, and computes Astraphe's backup sleep score from known duration versus baseline nightly need instead of using the provider `sleepScore`.

### `sleep_periods`

Per-period sleep records, including naps, linked to an athlete and source. Used when daily sleep has multiple periods or richer source details than the daily `biometrics` row captures.

Important fields:

- `id`
- `athlete_id`
- `date`
- `started_at`, `ended_at`
- `duration_min`
- `in_bed_min`
- `score`
- `deep_pct`, `rem_pct`, `light_pct`, `awake_pct`
- `is_nap` — default `false`
- `source`
- `external_id` — unique together with `source`

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
- `status`
- `completed_workout_id`
- `generated_by`

There is no `training_plans.goal` or `training_plans.context` column — `20260504153000_training_plans_add_structure.sql` added only `primary_zone` and `structure`. `structure` stores structured intervals as JSONB.

## Integrations

### `oauth_tokens`

Stores third-party tokens by athlete/provider.

Providers currently include WHOOP, Garmin-related flows, Strava, and Intervals.icu. Token access is server-side; clients never receive OAuth/API tokens.

Important fields:

- `athlete_id`
- `provider`
- `external_user_id`
- `access_token`
- `refresh_token`
- `expires_at`
- `refresh_lock_expires_at` — default `1970-01-01T00:00:00Z`; used to prevent concurrent refresh races (`20260708190000_oauth_token_refresh_lock.sql`)

There is no `oauth_tokens.scope` column — the only `scope` in the codebase is an OAuth *request* parameter (`backend/app/routers/sync.py`), not a stored value. Unique on `(athlete_id, provider)`.

### `activity_streams`

Stores heavy per-second activity streams separately from `workouts`. Strava and Intervals.icu stream bundles are normalized into a flat `time_series` JSON object and stored as gzip JSON in Supabase Storage.
Intervals.icu HR streams also refresh workout `avg_hr`, `max_hr`, `hr_zone_*_pct`, and `strain_score` using the athlete's current zone anchors. Activity summaries can refresh `athletes.max_hr`, `athletes.resting_hr`, and estimated `athletes.threshold_hr` when Intervals.icu provides those values.

Important fields:

- `workout_id`
- `athlete_id`
- `time_series` — legacy inline JSONB, usually `NULL` after gzip storage migration
- `storage_path` — `{athlete_id}/{workout_id}.json.gz` object in bucket `activity-streams`
- `byte_size`
- `content_encoding`
- `resolution_seconds`

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
- `platform` — must be `ios`, `android`, or `web`
- `token`
- timestamps (`created_at`, `updated_at`)

Unique on `(athlete_id, token)`. Protected by RLS so athletes manage their own token rows (policy `push_tokens_athlete_access`).

## Coach And AI

### `coach_conversations`

Conversation thread metadata:

- `id`
- `athlete_id`
- `title`
- timestamps

### `coach_messages`

Individual messages within a conversation:

- `conversation_id`
- `athlete_id`
- `role` — must be `user`, `ai`, or `system` (not `assistant`)
- `content`
- `image_urls`
- `created_at` only — no `updated_at` on this table

### `coach_memories`

Long-term coach memory with pgvector embeddings.

Important fields:

- `athlete_id`
- `content`
- `memory_type` — must be `note`, `race`, or `NULL`
- `entity_key`
- `event_date`
- `embedding vector(3072)`
- timestamps (`created_at`, `updated_at`)

There is no `coach_memories.context_date` or `coach_memories.metadata` column — the real columns are `event_date` and `entity_key` (`20260527160000`). Do not assume an HNSW index exists — `20260520140000` dropped and re-added `embedding` with no index (HNSW caps at 2000 dims; this column is 3072), so similarity search runs unindexed unless a later migration changes that.

### `athlete_analyses`

Cached screen-level AI analysis results.

Important fields:

- `athlete_id`
- `analysis_type` — one of `recovery`, `sleep`, `strain`, `training_load`, `dashboard_summary`, `workout`, `time_in_zones`
- `scope_key`
- `fingerprint`
- `content`
- `model`
- timestamps

Unique on `(athlete_id, analysis_type, scope_key)`. Used by `/v1/analysis/*` routes to avoid repeated LLM calls when source data has not changed.

## Storage

Coach uploads use the `coach-uploads` bucket and path prefixes based on the authenticated user/conversation. `20260519120000_coach_uploads_private.sql` sets the bucket `public = false` unconditionally — it is not ambiguous or migration-dependent. The frontend upload helper (`mobile/src/lib/api.ts`, `uploadCoachImage`) uses `createSignedUrl()` with a one-year TTL rather than `getPublicUrl()`, since the bucket is private and the resulting URL gets persisted in `coach_messages.image_urls` for later display, not just used immediately after upload.

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
