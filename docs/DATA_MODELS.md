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

- `tier` — `free`, `trial`, or `premium`
- `trial_ends_at` — set for new accounts (14-day trial, `20261104090000_default_new_users_to_trial.sql`); once it passes the backend treats the account as free and writes `tier = 'free'` back
- `gemini_model`
- `gemini_analysis_model`
- `rate_limit_rpm`
- `rate_limit_rph`
- `is_admin`

`user_metadata` is not trusted for authorization. `athletes.tier` mirrors the app-metadata tier (default `trial`) and can only be changed by the service role, but backend authorization/model/rate-limit decisions read app metadata.

## RLS Pattern

Every public table has RLS enabled. Athlete-owned tables generally use this ownership pattern:

```sql
athlete_id IN (
  SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())
)
```

Details that matter if you're writing a new policy:

- `auth.uid()` is wrapped in `(SELECT ...)` deliberately — this caches it once per statement (Postgres "initplan") instead of re-evaluating per row. `20260526233437_rls_policy_performance_fixes.sql` and `20260527014001_fix_rls_initplan_and_duplicate_indexes.sql` rewrote every policy to this form after the unwrapped version caused per-row re-evaluation at scale. Don't reintroduce the bare form.
- The policies rewritten by those migrations are scoped `TO authenticated` and pair `USING` with a matching `WITH CHECK`. Tables added since (`sleep_stage_segments`, `heart_rate_series`, `hr_detection_dismissals`, `weigh_ins`) use a single `FOR ALL USING (...)` policy, where Postgres applies `USING` as the check.
- Some tables are written only by the API's service role and give users `SELECT` alone (`oauth_tokens` — and only its non-secret columns — `notification_log`, `athlete_anchor_history`) or no policy at all (`messaging_events`).
- `20261103090000_security_hardening.sql` added restrictive `no_oauth_client_insert/update/delete` policies that block writes made with third-party OAuth (MCP) tokens (JWTs with a `client_id` claim). It applied them to the tables that existed then; tables created later don't have them.
- `anon` has no table privileges.

The API also scopes every request by resolved athlete ID and queries through a Supabase client carrying the user's JWT, so RLS remains active. Background jobs and server-owned writes use the service-role client.

## Core Tables

### `athletes`

One row per application user, created by the `handle_new_user` trigger on `auth.users` and updated through profile routes.

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
- `goal_weight_kg` — nullable, 20–350 (`20261109100000_weigh_ins.sql`)
- `max_hr`, `max_hr_source` — `manual` or `estimated` (`20261107100000_max_hr_source.sql`); an estimated value can be raised by a later, higher recorded HR, a manual one is never changed
- `resting_hr`, `resting_hr_source` — `measured` (the 42-day mean of the wearable's daily resting HR, updated as days sync) or `manual` (entered by the athlete, never replaced) (`20261109110000_resting_hr_source.sql`)
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
- `tier` — default `trial`
- `created_at` only — no `updated_at` on this table

A trigger (`protect_athlete_server_columns`) rejects changes to `tier`, `strava_athlete_id`, and `user_id` made with a user session.

Allowed `hr_zone_method` values are `lthr`, `hrr`, and `max_hr`. There is no `athletes.training_zones` column — zone data is derived (`zone_method`/`lthr`) or lives on `training_plans.target_zones`.

### `athlete_anchor_history`

Dated history of the anchors workout TSS is scored with, so changing FTP doesn't re-score past workouts. Written by the service role only (`services/anchor_history.py`).

- `athlete_id`
- `effective_from` — unique with `athlete_id`
- `ftp_watts`, `threshold_pace`, `measurement_units`
- `source` — `initial`, `manual`, `garmin`, or `estimated`

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
- `calories`
- `strava_activity_id`, `garmin_activity_id` — each unique per athlete (`(athlete_id, strava_activity_id)`, `(athlete_id, garmin_activity_id)`)
- `primary_source`, `source_ids` — source merge metadata
- `strava_streams_fetched`, `raw_strava_payload`
- `intervals`, `intervals_source`, `splits_metric`, `splits_standard`
- `notified_at` — set by the first replica that texts the athlete about the workout (Photon channel), so it's sent once
- `fit_file_url` — optional URL/path to a **raw Garmin `.fit` artifact**. Not read by the backend and not the canonical stream store; canonical streams live in Supabase Storage bucket `activity-streams` as gzip JSON (`activity_streams.storage_path`).

Unique on `(athlete_id, source, external_id)`.

Allowed sources are `garmin`, `whoop`, `healthkit`, `manual`, `strava`, `intervals_icu`, and `hr_detected`. `hr_detected` rows are created by `services/hr_activity_detection.py` from the all-day heart rate series and rank last in source priority: a detection overlapping a recorded workout is never saved, and a recorded workout that arrives later replaces overlapping detections.

Allowed sports are:

```text
run, bike, swim, strength, row, mobility, other
```

Deleting a workout un-completes any `training_plans` row linked to it (trigger `workouts_unlink_plans`).

### `biometrics`

Daily physiological summaries. Unique on `(athlete_id, date)`.

There is no `biometrics.source` or `biometrics.external_id` column — those exist on `workouts` and `sleep_periods`, not here. Per-field provenance on this table is tracked via `metric_sources` instead (see below).

Important fields:

- `id`
- `athlete_id`
- `date`
- `hrv_rmssd`
- `hrv_source` — `whoop`, `garmin`, `healthkit`, `intervals_icu`, or `NULL`
- `resting_hr`
- `sleep_duration_min`
- `sleep_in_bed_min`
- `sleep_score`, `source_sleep_score` — `sleep_score` is Astraphe's normalized value; `source_sleep_score` is the provider's original, unmodified score (`20260429000000_unify_score_names.sql`). Same pairing for recovery below.
- `recovery_score`, `source_recovery_score`
- `sleep_deep_pct`, `sleep_rem_pct`, `sleep_light_pct`, `sleep_awake_pct`
- `sleep_bedtime`
- `sleep_wakeup`
- `skin_temp`
- `spo2_pct`
- `skin_temp_deviation_c`
- `readiness_score`
- `strain_score`
- `day_strain` — written by `services/day_strain.py`: workouts' zone minutes plus all-day heart-rate minutes outside workouts at or above half of max HR, on the same 0–100 strain scale
- `sleep_need_min`, `sleep_debt_min`
- `weight_kg`, `height_cm` — `weight_kg` is the one-per-day value the rest of the app reads; see `weigh_ins`
- `metric_sources` — JSONB per-field provenance used for quality-ranked biometrics merges

`skin_temp` stores absolute Celsius (renamed from `skin_temp_deviation` by `20260521130000_rename_skin_temp_column.sql`).
`skin_temp_deviation_c` (added by `20260829190000_biometrics_skin_temp_deviation.sql`) is the canonical
"delta from this athlete's own baseline" signal, comparable across providers regardless of whether the
source reports a deviation natively (Garmin's `avgSkinTempDeviationC`) or an absolute reading (WHOOP,
intervals.icu): `process_and_save_biometrics` normalizes the latter by subtracting a 7-day trailing
average of the athlete's own prior `skin_temp` values (mirrors the mobile recovery page's
`baselineAvg7d`/`signedDeltaVsBaseline`, excluding the current day from its own baseline).
Intervals.icu wellness rows may use `id` as the local wellness date; ingestion maps that to `biometrics.date` (there is no column that stores the original Intervals.icu id). If Intervals.icu supplies sleep duration without sleep-stage percentages, ingestion stores the duration, leaves stage percentages `NULL`, and computes Astraphe's backup sleep score from known duration versus baseline nightly need instead of using the provider `sleepScore`.

### `heart_rate_series`

All-day heart rate, one row per athlete + local calendar day + source (unique on `(athlete_id, date, source)`). Written from Garmin's daily heart rate (a fixed 2-minute grid, 720 samples a day) by `services/heart_rate_series.py`; read whole by `GET /v1/biometrics/heart-rate`, workout auto-detection, and day strain.

- `athlete_id`
- `date`
- `source` — when a day has several, `garmin` > `whoop` > `healthkit`
- `start_at`
- `offsets_sec INTEGER[]`, `bpm SMALLINT[]` — parallel arrays (seconds from `start_at`, bpm); a check keeps their lengths equal
- `resting_hr`
- `created_at`, `updated_at`

Garmin fills stretches with no optical signal by repeating the last value. Detection and day strain drop those flat runs (10+ samples within ±1 bpm) with `drop_flatlines`; the heart-rate chart still shows them.

### `hr_detection_dismissals`

Windows (`started_at`, `ended_at`) the athlete deleted an `hr_detected` workout from, so the next sync doesn't detect it again.

### `weigh_ins`

Individual weigh-ins for the Weight screen. Unique on `(athlete_id, source, external_id)`.

- `athlete_id`
- `date`, `measured_at`
- `weight_kg` (20–350), `body_fat_pct` (2–75, nullable)
- `source`, `external_id`
- `time_known` — `false` for readings without a real time of day (stored at local noon)
- `deleted_at` — soft delete, so the app can undo and a re-sync never resurrects a deleted reading

`biometrics.weight_kg` is recomputed from weigh-ins when the athlete logs or deletes one (`services/weight.py`). In the other direction, the `biometrics_weight_to_weigh_in` trigger turns any other write of `biometrics.weight_kg` (profile edit, WHOOP, `POST /v1/biometrics/daily`) into a weigh-in, skipping a device repeating its previous value. Garmin weigh-ins are saved directly.

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
- `external_id` — unique per `(athlete_id, source, external_id)`

### `sleep_stage_segments`

Hypnogram blocks, one row per contiguous stage: `athlete_id`, `date` (same wake-date key as `biometrics`), `source`, `stage` (`deep`, `light`, `rem`, `awake`), `start_at`, `end_at`. Unique on `(athlete_id, source, start_at)`.

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
- `status` — `planned`, `done`, `skipped`, or `modified`
- `completed_workout_id` — the recorded workout that completes the session; unique, `ON DELETE SET NULL`
- `link_source` — `auto` or `manual`
- `dismissed_workout_ids` — workouts never to auto-match to this session again
- `generated_by`

There is no `training_plans.goal` or `training_plans.context` column. `structure` stores structured intervals as JSONB. Plan ↔ workout linking lives in `services/plan_matching.py` (`20261106090000_plan_links.sql`).

## Integrations

### `oauth_tokens`

Stores third-party tokens by athlete/provider.

Providers are `whoop`, `garmin`, `strava`, and `intervals_icu`. Only the service role writes this table; users can read only non-secret columns (`id`, `athlete_id`, `provider`, `external_user_id`, `expires_at`, `created_at`, `updated_at`). Clients never receive OAuth/API tokens. `access_token`/`refresh_token` are Fernet-encrypted when `OAUTH_TOKEN_ENCRYPTION_KEY` is set (required in production).

Important fields:

- `athlete_id`
- `provider`
- `external_user_id` — unique per provider when set
- `access_token`
- `refresh_token`
- `expires_at`
- `refresh_lock_expires_at` — default `1970-01-01T00:00:00Z`; an atomic claim used to prevent concurrent token refreshes and, for Garmin, to let only one replica sync an athlete per poll tick (`20260708190000_oauth_token_refresh_lock.sql`)

There is no `oauth_tokens.scope` column. Unique on `(athlete_id, provider)`.

### `activity_streams`

Stores heavy per-second activity streams separately from `workouts`. Strava and Intervals.icu stream bundles are normalized into a flat `time_series` JSON object and stored as gzip JSON in Supabase Storage.
Intervals.icu HR streams also refresh workout `avg_hr`, `max_hr`, `hr_zone_*_pct`, and `strain_score` using the athlete's current zone anchors. Activity summaries can refresh `athletes.max_hr`, `athletes.resting_hr`, and estimated `athletes.threshold_hr` when Intervals.icu provides those values.

Important fields:

- `workout_id` — unique
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

### `notification_log`

One row per notification sent (`athlete_id`, `kind`, `dedupe_key`, optional `conversation_id`, `pushed`), unique on `(athlete_id, kind, dedupe_key)`. Claiming the row before sending is what keeps several API replicas from sending the same notification twice. Service-role writes; athletes can read their own rows.

### `messaging_events`

Inbound dedupe for the Photon (iMessage) channel: primary key `(provider, message_id)`. Service role only.

## Coach And AI

### `coach_conversations`

Conversation thread metadata:

- `id`
- `athlete_id`
- `title`
- `started_by` — `athlete` (default) or `coach`
- `trigger` — what started a coach thread, e.g. `debrief`, `missed`, `weekly`, `readiness`, `plan_changed`
- `context` — JSONB context card for the thread
- `unread`
- timestamps

### `coach_messages`

Individual messages within a conversation:

- `conversation_id`
- `athlete_id`
- `role` — must be `user`, `ai`, or `system` (not `assistant`); user sessions may only write `user` rows, coach/system turns are written by the service role
- `content`
- `image_urls`
- `attachments` — JSONB array (max 3) of `{name, kind, content}` extracted document text
- `quick_replies` — suggested one-tap replies
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

Coach uploads use the `coach-uploads` bucket and path prefixes based on the authenticated user/conversation. `20260519120000_coach_uploads_private.sql` sets the bucket `public = false` unconditionally. The frontend upload helper (`mobile/src/lib/api.ts`, `uploadCoachImage`) uses `createSignedUrl()` rather than `getPublicUrl()`, since the bucket is private and the resulting URL gets persisted in `coach_messages.image_urls` for later display.

Activity stream blobs live in the `activity-streams` bucket; only the service role writes them.

## Pydantic Models

Request/response schemas live in `backend/app/models/` and router-local models. Treat those as the API contract source when they differ from database column names.

Important files:

- `backend/app/models/athlete.py`
- `backend/app/models/workout.py`
- `backend/app/models/biometrics.py`
- `backend/app/routers/coach.py`
- `backend/app/routers/weight.py`
- `backend/app/routers/training_plans.py`
- `backend/app/routers/notifications.py`

## Schema Maintenance

When migrations change tables, update this document manually and optionally regenerate `docs/schema/astraphe_public_schema.sql` with `docs/tools/generate_schema.py`.
