-- ASTRAPHE AI Coach — public schema (generated)
-- Source: live PostgreSQL introspection via docs/tools/generate_schema.py
-- Generated: 2026-11-10 04:10:24 UTC
--
-- Prerequisites:
--   - Supabase local or hosted project with auth schema
--   - CREATE EXTENSION IF NOT EXISTS pgcrypto;
--
-- This file is ordered for execution (parents before children).
-- Re-run the generator after migrations to refresh: see docs/SCHEMA_TOOL.md

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.athletes (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  user_id uuid NOT NULL,
  display_name text NOT NULL,
  city text,
  country_code character(2),
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  date_of_birth date,
  weight_kg numeric(5,2),
  height_cm numeric(5,1),
  max_hr smallint,
  resting_hr smallint,
  ftp_watts smallint,
  threshold_hr smallint,
  threshold_pace text,
  vo2max_est numeric(4,1),
  sport_focus text[] DEFAULT '{run,bike}'::text[],
  weekly_tss_target smallint DEFAULT 400,
  hrv_baseline numeric(6,2),
  rhr_baseline smallint,
  notification_settings jsonb DEFAULT '{"coach": true, "insights": true, "workouts": false, "readiness": true}'::jsonb,
  privacy_settings jsonb DEFAULT '{"marketing": false, "share_data": true}'::jsonb,
  measurement_units text DEFAULT 'metric'::text NOT NULL,
  time_format text DEFAULT '12h'::text NOT NULL,
  gender text DEFAULT 'male'::text NOT NULL,
  timezone_offset_min integer DEFAULT 0 NOT NULL,
  tier text DEFAULT 'trial'::text NOT NULL,
  threshold_hr_source text,
  zone_method text GENERATED ALWAYS AS (
CASE
    WHEN ((threshold_hr IS NOT NULL) AND (threshold_hr > 0) AND (threshold_hr_source = 'manual'::text)) THEN 'lthr'::text
    WHEN ((max_hr IS NOT NULL) AND (max_hr > 0) AND (resting_hr IS NOT NULL) AND (resting_hr > 0) AND (max_hr > resting_hr)) THEN 'hrr'::text
    WHEN ((max_hr IS NOT NULL) AND (max_hr > 0)) THEN 'max_hr'::text
    ELSE NULL::text
END) STORED,
  lthr smallint GENERATED ALWAYS AS (threshold_hr) STORED,
  hr_zone_method text DEFAULT 'lthr'::text,
  strava_athlete_id bigint,
  max_hr_source text,
  goal_weight_kg numeric(5,2),
  resting_hr_source text,
  CONSTRAINT athletes_pkey PRIMARY KEY (id),
  CONSTRAINT athletes_strava_athlete_id_key UNIQUE (strava_athlete_id),
  CONSTRAINT athletes_user_id_unique UNIQUE (user_id),
  CONSTRAINT athletes_gender_check CHECK (lower(gender) = ANY (ARRAY['male'::text, 'female'::text])),
  CONSTRAINT athletes_goal_weight_kg_check CHECK (goal_weight_kg IS NULL OR goal_weight_kg >= 20::numeric AND goal_weight_kg <= 350::numeric),
  CONSTRAINT athletes_max_hr_source_check CHECK (max_hr_source IS NULL OR (max_hr_source = ANY (ARRAY['manual'::text, 'estimated'::text]))),
  CONSTRAINT athletes_resting_hr_source_check CHECK (resting_hr_source IS NULL OR (resting_hr_source = ANY (ARRAY['manual'::text, 'measured'::text]))),
  CONSTRAINT athletes_threshold_hr_source_check CHECK (threshold_hr_source IS NULL OR (threshold_hr_source = ANY (ARRAY['manual'::text, 'estimated'::text]))),
  CONSTRAINT athletes_tier_check CHECK (tier = ANY (ARRAY['free'::text, 'trial'::text, 'premium'::text])),
  CONSTRAINT hr_zone_method_valid CHECK (hr_zone_method IS NULL OR (hr_zone_method = ANY (ARRAY['lthr'::text, 'hrr'::text, 'max_hr'::text]))),
  CONSTRAINT athletes_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);



CREATE TABLE public.messaging_events (
  provider text NOT NULL,
  message_id text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT messaging_events_pkey PRIMARY KEY (provider, message_id)
);



CREATE TABLE public.athlete_analyses (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  analysis_type text NOT NULL,
  scope_key text NOT NULL,
  fingerprint text NOT NULL,
  model text,
  content text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT athlete_analyses_pkey PRIMARY KEY (id),
  CONSTRAINT athlete_analyses_unique_scope UNIQUE (athlete_id, analysis_type, scope_key),
  CONSTRAINT athlete_analyses_analysis_type_check CHECK (analysis_type = ANY (ARRAY['recovery'::text, 'sleep'::text, 'strain'::text, 'training_load'::text, 'dashboard_summary'::text, 'workout'::text, 'time_in_zones'::text])),
  CONSTRAINT athlete_analyses_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.athlete_anchor_history (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  effective_from date NOT NULL,
  ftp_watts smallint,
  threshold_pace text,
  measurement_units text,
  source text DEFAULT 'manual'::text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT athlete_anchor_history_pkey PRIMARY KEY (id),
  CONSTRAINT athlete_anchor_history_athlete_id_effective_from_key UNIQUE (athlete_id, effective_from),
  CONSTRAINT athlete_anchor_history_source_check CHECK (source = ANY (ARRAY['initial'::text, 'manual'::text, 'garmin'::text, 'estimated'::text])),
  CONSTRAINT athlete_anchor_history_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.biometrics (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  hrv_rmssd numeric(6,2),
  hrv_source text,
  resting_hr smallint,
  sleep_duration_min smallint,
  source_sleep_score smallint,
  sleep_deep_pct numeric(4,1),
  sleep_rem_pct numeric(4,1),
  sleep_light_pct numeric(4,1),
  sleep_awake_pct numeric(4,1),
  sleep_bedtime timestamp with time zone,
  sleep_wakeup timestamp with time zone,
  skin_temp numeric(4,2),
  spo2_pct numeric(4,1),
  source_recovery_score smallint,
  sleep_score smallint,
  recovery_score smallint,
  day_strain numeric(4,1),
  sleep_need_min smallint,
  sleep_debt_min smallint,
  readiness_score smallint,
  strain_score smallint,
  sleep_in_bed_min smallint,
  weight_kg numeric(5,2),
  height_cm numeric(5,1),
  metric_sources jsonb DEFAULT '{}'::jsonb NOT NULL,
  skin_temp_deviation_c numeric(4,2),
  CONSTRAINT biometrics_pkey PRIMARY KEY (id),
  CONSTRAINT biometrics_athlete_date_unique UNIQUE (athlete_id, date),
  CONSTRAINT biometrics_hrv_source_check CHECK (hrv_source IS NULL OR (hrv_source = ANY (ARRAY['whoop'::text, 'garmin'::text, 'healthkit'::text, 'intervals_icu'::text]))),
  CONSTRAINT biometrics_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.coach_conversations (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  title text,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  started_by text DEFAULT 'athlete'::text NOT NULL,
  trigger text,
  context jsonb,
  unread boolean DEFAULT false NOT NULL,
  CONSTRAINT coach_conversations_pkey PRIMARY KEY (id),
  CONSTRAINT coach_conversations_started_by_check CHECK (started_by = ANY (ARRAY['athlete'::text, 'coach'::text])),
  CONSTRAINT coach_conversations_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.coach_memories (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  content text NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  embedding vector(3072),
  memory_type text,
  entity_key text,
  event_date date,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT coach_memories_pkey PRIMARY KEY (id),
  CONSTRAINT coach_memories_memory_type_check CHECK (memory_type IS NULL OR (memory_type = ANY (ARRAY['note'::text, 'race'::text]))),
  CONSTRAINT coach_memories_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.heart_rate_series (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  source text NOT NULL,
  start_at timestamp with time zone NOT NULL,
  offsets_sec integer[] NOT NULL,
  bpm smallint[] NOT NULL,
  resting_hr smallint,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT heart_rate_series_pkey PRIMARY KEY (id),
  CONSTRAINT heart_rate_series_unique UNIQUE (athlete_id, date, source),
  CONSTRAINT heart_rate_series_lengths CHECK (cardinality(offsets_sec) = cardinality(bpm)),
  CONSTRAINT heart_rate_series_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.hr_detection_dismissals (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  started_at timestamp with time zone NOT NULL,
  ended_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT hr_detection_dismissals_pkey PRIMARY KEY (id),
  CONSTRAINT hr_detection_dismissals_order CHECK (ended_at > started_at),
  CONSTRAINT hr_detection_dismissals_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.oauth_tokens (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  provider text NOT NULL,
  external_user_id text,
  access_token text NOT NULL,
  refresh_token text,
  expires_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  refresh_lock_expires_at timestamp with time zone DEFAULT '1970-01-01 00:00:00+00'::timestamp with time zone NOT NULL,
  CONSTRAINT oauth_tokens_pkey PRIMARY KEY (id),
  CONSTRAINT oauth_tokens_athlete_provider_unique UNIQUE (athlete_id, provider),
  CONSTRAINT oauth_tokens_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.push_tokens (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  token text NOT NULL,
  platform text NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT push_tokens_pkey PRIMARY KEY (id),
  CONSTRAINT push_tokens_athlete_id_token_key UNIQUE (athlete_id, token),
  CONSTRAINT push_tokens_platform_check CHECK (platform = ANY (ARRAY['ios'::text, 'android'::text, 'web'::text])),
  CONSTRAINT push_tokens_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.sleep_periods (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  started_at timestamp with time zone NOT NULL,
  ended_at timestamp with time zone NOT NULL,
  duration_min smallint NOT NULL,
  score smallint,
  deep_pct numeric(4,1),
  rem_pct numeric(4,1),
  light_pct numeric(4,1),
  awake_pct numeric(4,1),
  is_nap boolean DEFAULT false,
  source text NOT NULL,
  external_id text,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  in_bed_min smallint,
  CONSTRAINT sleep_periods_pkey PRIMARY KEY (id),
  CONSTRAINT sleep_periods_athlete_source_external_uniq UNIQUE (athlete_id, source, external_id),
  CONSTRAINT sleep_periods_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.sleep_stage_segments (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  source text NOT NULL,
  stage text NOT NULL,
  start_at timestamp with time zone NOT NULL,
  end_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT sleep_stage_segments_pkey PRIMARY KEY (id),
  CONSTRAINT sleep_stage_segments_unique UNIQUE (athlete_id, source, start_at),
  CONSTRAINT sleep_stage_segments_order CHECK (end_at > start_at),
  CONSTRAINT sleep_stage_segments_stage_check CHECK (stage = ANY (ARRAY['deep'::text, 'light'::text, 'rem'::text, 'awake'::text])),
  CONSTRAINT sleep_stage_segments_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.tss_history (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  daily_tss numeric(7,2) DEFAULT 0 NOT NULL,
  workout_ids uuid[],
  ctl numeric(6,2),
  atl numeric(6,2),
  tsb numeric(7,2),
  CONSTRAINT tss_history_pkey PRIMARY KEY (id),
  CONSTRAINT tss_history_athlete_date_unique UNIQUE (athlete_id, date),
  CONSTRAINT tss_history_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.weigh_ins (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  date date NOT NULL,
  measured_at timestamp with time zone NOT NULL,
  weight_kg numeric(5,2) NOT NULL,
  body_fat_pct numeric(4,1),
  source text NOT NULL,
  external_id text NOT NULL,
  time_known boolean DEFAULT true NOT NULL,
  deleted_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT weigh_ins_pkey PRIMARY KEY (id),
  CONSTRAINT weigh_ins_unique UNIQUE (athlete_id, source, external_id),
  CONSTRAINT weigh_ins_body_fat_pct_check CHECK (body_fat_pct IS NULL OR body_fat_pct >= 2::numeric AND body_fat_pct <= 75::numeric),
  CONSTRAINT weigh_ins_weight_kg_check CHECK (weight_kg >= 20::numeric AND weight_kg <= 350::numeric),
  CONSTRAINT weigh_ins_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.workouts (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  source text NOT NULL,
  external_id text,
  sport text NOT NULL,
  title text,
  started_at timestamp with time zone NOT NULL,
  ended_at timestamp with time zone NOT NULL,
  distance_m numeric(10,2),
  elevation_gain_m numeric(8,2),
  avg_hr smallint,
  max_hr smallint,
  avg_power_w smallint,
  norm_power_w smallint,
  avg_pace_sec_km smallint,
  tss numeric(6,2),
  if_value numeric(4,3),
  fit_file_url text,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  hr_zone_1_pct smallint,
  hr_zone_2_pct smallint,
  hr_zone_3_pct smallint,
  hr_zone_4_pct smallint,
  hr_zone_5_pct smallint,
  strain_score smallint,
  hr_zone_0_pct smallint,
  duration_seconds integer,
  strava_activity_id bigint,
  strava_streams_fetched boolean DEFAULT false,
  primary_source text DEFAULT 'manual'::text,
  source_ids jsonb DEFAULT '{}'::jsonb,
  raw_strava_payload jsonb,
  intervals jsonb,
  intervals_source text,
  splits_metric jsonb,
  splits_standard jsonb,
  garmin_activity_id bigint,
  calories numeric(8,1),
  notified_at timestamp with time zone,
  CONSTRAINT workouts_pkey PRIMARY KEY (id),
  CONSTRAINT workouts_athlete_garmin_activity_uniq UNIQUE (athlete_id, garmin_activity_id),
  CONSTRAINT workouts_athlete_source_external_uniq UNIQUE (athlete_id, source, external_id),
  CONSTRAINT workouts_athlete_strava_activity_uniq UNIQUE (athlete_id, strava_activity_id),
  CONSTRAINT workouts_source_check CHECK (source = ANY (ARRAY['garmin'::text, 'whoop'::text, 'healthkit'::text, 'manual'::text, 'strava'::text, 'intervals_icu'::text, 'hr_detected'::text])),
  CONSTRAINT workouts_sport_check CHECK (sport = ANY (ARRAY['run'::text, 'bike'::text, 'swim'::text, 'strength'::text, 'row'::text, 'mobility'::text, 'other'::text])),
  CONSTRAINT workouts_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
);



CREATE TABLE public.coach_messages (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  conversation_id uuid NOT NULL,
  athlete_id uuid NOT NULL,
  role text NOT NULL,
  content text,
  image_urls text[] DEFAULT '{}'::text[] NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  attachments jsonb DEFAULT '[]'::jsonb NOT NULL,
  quick_replies text[] DEFAULT '{}'::text[] NOT NULL,
  CONSTRAINT coach_messages_pkey PRIMARY KEY (id),
  CONSTRAINT coach_messages_attachments_is_array CHECK (jsonb_typeof(attachments) = 'array'::text AND jsonb_array_length(attachments) <= 3),
  CONSTRAINT coach_messages_role_check CHECK (role = ANY (ARRAY['user'::text, 'ai'::text, 'system'::text])),
  CONSTRAINT coach_messages_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE,
  CONSTRAINT coach_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES coach_conversations(id) ON DELETE CASCADE
);



CREATE TABLE public.notification_log (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  kind text NOT NULL,
  dedupe_key text NOT NULL,
  conversation_id uuid,
  pushed boolean DEFAULT false NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT notification_log_pkey PRIMARY KEY (id),
  CONSTRAINT notification_log_athlete_id_kind_dedupe_key_key UNIQUE (athlete_id, kind, dedupe_key),
  CONSTRAINT notification_log_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE,
  CONSTRAINT notification_log_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES coach_conversations(id) ON DELETE SET NULL
);



CREATE TABLE public.activity_laps (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  workout_id uuid NOT NULL,
  athlete_id uuid NOT NULL,
  lap_index integer,
  start_index integer,
  end_index integer,
  elapsed_time integer,
  moving_time integer,
  distance double precision,
  average_heartrate double precision,
  max_heartrate double precision,
  average_watts double precision,
  average_cadence double precision,
  average_speed double precision,
  total_elevation_gain double precision,
  raw_lap jsonb,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT activity_laps_pkey PRIMARY KEY (id),
  CONSTRAINT activity_laps_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE,
  CONSTRAINT activity_laps_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);



CREATE TABLE public.activity_streams (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  workout_id uuid NOT NULL,
  athlete_id uuid NOT NULL,
  time_series jsonb,
  resolution_seconds integer DEFAULT 1,
  created_at timestamp with time zone DEFAULT now(),
  storage_path text,
  byte_size bigint,
  content_encoding text DEFAULT 'gzip'::text,
  CONSTRAINT activity_streams_pkey PRIMARY KEY (id),
  CONSTRAINT activity_streams_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE,
  CONSTRAINT activity_streams_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);



CREATE TABLE public.training_plans (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  athlete_id uuid NOT NULL,
  planned_date date NOT NULL,
  sport text NOT NULL,
  title text NOT NULL,
  description text,
  duration_min smallint,
  target_tss smallint,
  target_zones jsonb,
  status text DEFAULT 'planned'::text NOT NULL,
  completed_workout_id uuid,
  generated_by text DEFAULT 'astraphe_ai'::text,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  primary_zone text,
  structure jsonb,
  link_source text,
  dismissed_workout_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
  CONSTRAINT training_plans_pkey PRIMARY KEY (id),
  CONSTRAINT training_plans_link_source_check CHECK (link_source IS NULL OR (link_source = ANY (ARRAY['auto'::text, 'manual'::text]))),
  CONSTRAINT training_plans_status_check CHECK (status = ANY (ARRAY['planned'::text, 'done'::text, 'skipped'::text, 'modified'::text])),
  CONSTRAINT training_plans_athlete_id_fkey FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE,
  CONSTRAINT training_plans_completed_workout_id_fkey FOREIGN KEY (completed_workout_id) REFERENCES workouts(id) ON DELETE SET NULL
);



-- Indexes

CREATE INDEX athlete_analyses_athlete_type_scope ON public.athlete_analyses USING btree (athlete_id, analysis_type, scope_key);

CREATE INDEX athlete_analyses_athlete_updated ON public.athlete_analyses USING btree (athlete_id, updated_at DESC);

CREATE INDEX athlete_anchor_history_athlete_idx ON public.athlete_anchor_history USING btree (athlete_id, effective_from DESC);

CREATE INDEX biometrics_athlete_date ON public.biometrics USING btree (athlete_id, date DESC);

CREATE INDEX coach_conversations_athlete_updated ON public.coach_conversations USING btree (athlete_id, updated_at DESC);

CREATE INDEX coach_memories_athlete_idx ON public.coach_memories USING btree (athlete_id, created_at DESC);

CREATE INDEX coach_memories_entity_idx ON public.coach_memories USING btree (athlete_id, memory_type, entity_key, updated_at DESC);

CREATE INDEX hr_detection_dismissals_athlete_started ON public.hr_detection_dismissals USING btree (athlete_id, started_at);

CREATE UNIQUE INDEX oauth_tokens_provider_external_user_uniq ON public.oauth_tokens USING btree (provider, external_user_id) WHERE (external_user_id IS NOT NULL);

CREATE INDEX push_tokens_athlete_idx ON public.push_tokens USING btree (athlete_id);

CREATE INDEX sleep_periods_athlete_date ON public.sleep_periods USING btree (athlete_id, date DESC);

CREATE INDEX sleep_stage_segments_athlete_date ON public.sleep_stage_segments USING btree (athlete_id, date);

CREATE INDEX tss_history_athlete_date ON public.tss_history USING btree (athlete_id, date DESC);

CREATE INDEX weigh_ins_athlete_measured ON public.weigh_ins USING btree (athlete_id, measured_at DESC);

CREATE INDEX idx_workouts_garmin_id ON public.workouts USING btree (garmin_activity_id) WHERE (garmin_activity_id IS NOT NULL);

CREATE INDEX idx_workouts_strava_id ON public.workouts USING btree (strava_activity_id) WHERE (strava_activity_id IS NOT NULL);

CREATE INDEX workouts_athlete_started_at ON public.workouts USING btree (athlete_id, started_at DESC);

CREATE INDEX coach_messages_athlete_created ON public.coach_messages USING btree (athlete_id, created_at DESC);

CREATE INDEX coach_messages_conversation_created ON public.coach_messages USING btree (conversation_id, created_at);

CREATE INDEX idx_activity_laps_workout ON public.activity_laps USING btree (workout_id, lap_index);

CREATE INDEX idx_activity_streams_workout ON public.activity_streams USING btree (workout_id);

CREATE UNIQUE INDEX idx_activity_streams_workout_unique ON public.activity_streams USING btree (workout_id);

CREATE INDEX training_plans_athlete_date_idx ON public.training_plans USING btree (athlete_id, planned_date);

CREATE UNIQUE INDEX training_plans_completed_workout_unique ON public.training_plans USING btree (completed_workout_id) WHERE (completed_workout_id IS NOT NULL);
