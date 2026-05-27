


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "extensions";






CREATE OR REPLACE FUNCTION "public"."handle_new_user"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'public'
    AS $$
BEGIN
  INSERT INTO public.athletes (user_id, display_name)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1))
  );
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_new_user"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."match_coach_memories"("athlete_id" "uuid", "query_embedding" double precision[], "match_threshold" double precision DEFAULT 0.50, "match_count" integer DEFAULT 5) RETURNS TABLE("id" "uuid", "content" "text", "similarity" double precision, "created_at" timestamp with time zone)
    LANGUAGE "sql" STABLE
    SET "search_path" TO 'public', 'extensions'
    AS $$
    SELECT
        m.id,
        m.content,
        1 - (m.embedding <=> query_embedding::extensions.vector) AS similarity,
        m.created_at
    FROM coach_memories m
    WHERE m.athlete_id = match_coach_memories.athlete_id
      AND 1 - (m.embedding <=> query_embedding::extensions.vector) > match_threshold
    ORDER BY m.embedding <=> query_embedding::extensions.vector
    LIMIT match_count;
$$;


ALTER FUNCTION "public"."match_coach_memories"("athlete_id" "uuid", "query_embedding" double precision[], "match_threshold" double precision, "match_count" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."rls_auto_enable"() RETURNS "event_trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'pg_catalog'
    AS $$
DECLARE
  cmd record;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        EXECUTE format('alter table if exists %s enable row level security', cmd.object_identity);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
$$;


ALTER FUNCTION "public"."rls_auto_enable"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."activity_laps" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workout_id" "uuid" NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "lap_index" integer,
    "start_index" integer,
    "end_index" integer,
    "elapsed_time" integer,
    "moving_time" integer,
    "distance" double precision,
    "average_heartrate" double precision,
    "max_heartrate" double precision,
    "average_watts" double precision,
    "average_cadence" double precision,
    "average_speed" double precision,
    "total_elevation_gain" double precision,
    "raw_lap" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."activity_laps" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."activity_streams" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "workout_id" "uuid" NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "time_series" "jsonb" NOT NULL,
    "resolution_seconds" integer DEFAULT 1,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."activity_streams" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."athlete_analyses" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "analysis_type" "text" NOT NULL,
    "scope_key" "text" NOT NULL,
    "fingerprint" "text" NOT NULL,
    "model" "text",
    "content" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "athlete_analyses_analysis_type_check" CHECK (("analysis_type" = ANY (ARRAY['recovery'::"text", 'sleep'::"text", 'strain'::"text", 'training_load'::"text", 'dashboard_summary'::"text", 'workout'::"text", 'time_in_zones'::"text"])))
);


ALTER TABLE "public"."athlete_analyses" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."athletes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "display_name" "text" NOT NULL,
    "city" "text",
    "country_code" character(2),
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "date_of_birth" "date",
    "weight_kg" numeric(5,2),
    "height_cm" numeric(5,1),
    "max_hr" smallint,
    "resting_hr" smallint,
    "ftp_watts" smallint,
    "threshold_hr" smallint,
    "threshold_pace" "text",
    "vo2max_est" numeric(4,1),
    "sport_focus" "text"[] DEFAULT '{run,bike}'::"text"[],
    "weekly_tss_target" smallint DEFAULT 400,
    "hrv_baseline" numeric(6,2),
    "rhr_baseline" smallint,
    "notification_settings" "jsonb" DEFAULT '{"coach": true, "insights": true, "workouts": false, "readiness": true}'::"jsonb",
    "privacy_settings" "jsonb" DEFAULT '{"marketing": false, "share_data": true}'::"jsonb",
    "measurement_units" "text" DEFAULT 'metric'::"text" NOT NULL,
    "time_format" "text" DEFAULT '12h'::"text" NOT NULL,
    "gender" "text" DEFAULT 'male'::"text" NOT NULL,
    "timezone_offset_min" integer DEFAULT 0 NOT NULL,
    "tier" "text" DEFAULT 'free'::"text" NOT NULL,
    "threshold_hr_source" "text",
    "zone_method" "text" GENERATED ALWAYS AS (
CASE
    WHEN (("threshold_hr" IS NOT NULL) AND ("threshold_hr" > 0) AND ("threshold_hr_source" = 'manual'::"text")) THEN 'lthr'::"text"
    WHEN (("max_hr" IS NOT NULL) AND ("max_hr" > 0) AND ("resting_hr" IS NOT NULL) AND ("resting_hr" > 0) AND ("max_hr" > "resting_hr")) THEN 'hrr'::"text"
    WHEN (("max_hr" IS NOT NULL) AND ("max_hr" > 0)) THEN 'max_hr'::"text"
    ELSE NULL::"text"
END) STORED,
    "lthr" smallint GENERATED ALWAYS AS ("threshold_hr") STORED,
    "hr_zone_method" "text" DEFAULT 'lthr'::"text",
    "strava_athlete_id" bigint,
    CONSTRAINT "athletes_gender_check" CHECK (("lower"("gender") = ANY (ARRAY['male'::"text", 'female'::"text"]))),
    CONSTRAINT "athletes_threshold_hr_source_check" CHECK ((("threshold_hr_source" IS NULL) OR ("threshold_hr_source" = ANY (ARRAY['manual'::"text", 'estimated'::"text"])))),
    CONSTRAINT "athletes_tier_check" CHECK (("tier" = ANY (ARRAY['free'::"text", 'trial'::"text", 'premium'::"text"]))),
    CONSTRAINT "hr_zone_method_valid" CHECK ((("hr_zone_method" IS NULL) OR ("hr_zone_method" = ANY (ARRAY['lthr'::"text", 'hrr'::"text", 'max_hr'::"text"]))))
);


ALTER TABLE "public"."athletes" OWNER TO "postgres";


COMMENT ON COLUMN "public"."athletes"."threshold_hr_source" IS 'manual = user-entered LTHR; estimated = pipeline-derived';



COMMENT ON COLUMN "public"."athletes"."zone_method" IS 'Derived tier used for HR zones display (lthr|hrr|max_hr)';



CREATE TABLE IF NOT EXISTS "public"."biometrics" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "date" "date" NOT NULL,
    "hrv_rmssd" numeric(6,2),
    "hrv_source" "text",
    "resting_hr" smallint,
    "sleep_duration_min" smallint,
    "source_sleep_score" smallint,
    "sleep_deep_pct" numeric(4,1),
    "sleep_rem_pct" numeric(4,1),
    "sleep_light_pct" numeric(4,1),
    "sleep_awake_pct" numeric(4,1),
    "sleep_bedtime" timestamp with time zone,
    "sleep_wakeup" timestamp with time zone,
    "skin_temp" numeric(4,2),
    "spo2_pct" numeric(4,1),
    "source_recovery_score" smallint,
    "sleep_score" smallint,
    "recovery_score" smallint,
    "day_strain" numeric(4,1),
    "sleep_need_min" smallint,
    "sleep_debt_min" smallint,
    "readiness_score" smallint,
    "strain_score" smallint,
    "sleep_in_bed_min" smallint,
    CONSTRAINT "biometrics_hrv_source_check" CHECK (("hrv_source" = ANY (ARRAY['whoop'::"text", 'garmin'::"text", 'healthkit'::"text"])))
);


ALTER TABLE "public"."biometrics" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."coach_conversations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "title" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."coach_conversations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."coach_memories" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "content" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "embedding" "extensions"."vector"(3072)
);


ALTER TABLE "public"."coach_memories" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."coach_messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "content" "text",
    "image_urls" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "coach_messages_role_check" CHECK (("role" = ANY (ARRAY['user'::"text", 'ai'::"text", 'system'::"text"])))
);


ALTER TABLE "public"."coach_messages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."oauth_tokens" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "provider" "text" NOT NULL,
    "external_user_id" "text",
    "access_token" "text" NOT NULL,
    "refresh_token" "text",
    "expires_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."oauth_tokens" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."push_tokens" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "token" "text" NOT NULL,
    "platform" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "push_tokens_platform_check" CHECK (("platform" = ANY (ARRAY['ios'::"text", 'android'::"text", 'web'::"text"])))
);


ALTER TABLE "public"."push_tokens" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."sleep_periods" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "date" "date" NOT NULL,
    "started_at" timestamp with time zone NOT NULL,
    "ended_at" timestamp with time zone NOT NULL,
    "duration_min" smallint NOT NULL,
    "score" smallint,
    "deep_pct" numeric(4,1),
    "rem_pct" numeric(4,1),
    "light_pct" numeric(4,1),
    "awake_pct" numeric(4,1),
    "is_nap" boolean DEFAULT false,
    "source" "text" NOT NULL,
    "external_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "in_bed_min" smallint
);


ALTER TABLE "public"."sleep_periods" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."training_plans" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "planned_date" "date" NOT NULL,
    "sport" "text" NOT NULL,
    "title" "text" NOT NULL,
    "description" "text",
    "duration_min" smallint,
    "target_tss" smallint,
    "target_zones" "jsonb",
    "status" "text" DEFAULT 'planned'::"text" NOT NULL,
    "completed_workout_id" "uuid",
    "generated_by" "text" DEFAULT 'astrape_ai'::"text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "primary_zone" "text",
    "structure" "jsonb",
    CONSTRAINT "training_plans_status_check" CHECK (("status" = ANY (ARRAY['planned'::"text", 'done'::"text", 'skipped'::"text", 'modified'::"text"])))
);


ALTER TABLE "public"."training_plans" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tss_history" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "date" "date" NOT NULL,
    "daily_tss" numeric(7,2) DEFAULT 0 NOT NULL,
    "workout_ids" "uuid"[],
    "ctl" numeric(6,2),
    "atl" numeric(6,2),
    "tsb" numeric(7,2)
);


ALTER TABLE "public"."tss_history" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."workouts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "athlete_id" "uuid" NOT NULL,
    "source" "text" NOT NULL,
    "external_id" "text",
    "sport" "text" NOT NULL,
    "title" "text",
    "started_at" timestamp with time zone NOT NULL,
    "ended_at" timestamp with time zone NOT NULL,
    "distance_m" numeric(10,2),
    "elevation_gain_m" numeric(8,2),
    "avg_hr" smallint,
    "max_hr" smallint,
    "avg_power_w" smallint,
    "norm_power_w" smallint,
    "avg_pace_sec_km" smallint,
    "tss" numeric(6,2),
    "if_value" numeric(4,3),
    "fit_file_url" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "hr_zone_1_pct" smallint,
    "hr_zone_2_pct" smallint,
    "hr_zone_3_pct" smallint,
    "hr_zone_4_pct" smallint,
    "hr_zone_5_pct" smallint,
    "strain_score" smallint,
    "hr_zone_0_pct" smallint,
    "duration_seconds" integer,
    "strava_activity_id" bigint,
    "strava_streams_fetched" boolean DEFAULT false,
    "primary_source" "text" DEFAULT 'manual'::"text",
    "source_ids" "jsonb" DEFAULT '{}'::"jsonb",
    "raw_strava_payload" "jsonb",
    "intervals" "jsonb",
    "intervals_source" "text",
    "splits_metric" "jsonb",
    "splits_standard" "jsonb",
    CONSTRAINT "workouts_source_check" CHECK (("source" = ANY (ARRAY['garmin'::"text", 'whoop'::"text", 'healthkit'::"text", 'manual'::"text", 'strava'::"text"]))),
    CONSTRAINT "workouts_sport_check" CHECK (("sport" = ANY (ARRAY['run'::"text", 'bike'::"text", 'swim'::"text", 'strength'::"text", 'row'::"text", 'mobility'::"text", 'other'::"text"])))
);


ALTER TABLE "public"."workouts" OWNER TO "postgres";


COMMENT ON COLUMN "public"."workouts"."hr_zone_1_pct" IS 'Percentage of time spent in heart rate zone 1';



COMMENT ON COLUMN "public"."workouts"."hr_zone_2_pct" IS 'Percentage of time spent in heart rate zone 2';



COMMENT ON COLUMN "public"."workouts"."hr_zone_3_pct" IS 'Percentage of time spent in heart rate zone 3';



COMMENT ON COLUMN "public"."workouts"."hr_zone_4_pct" IS 'Percentage of time spent in heart rate zone 4';



COMMENT ON COLUMN "public"."workouts"."hr_zone_5_pct" IS 'Percentage of time spent in heart rate zone 5';



ALTER TABLE ONLY "public"."activity_laps"
    ADD CONSTRAINT "activity_laps_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."activity_streams"
    ADD CONSTRAINT "activity_streams_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."athlete_analyses"
    ADD CONSTRAINT "athlete_analyses_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."athlete_analyses"
    ADD CONSTRAINT "athlete_analyses_unique_scope" UNIQUE ("athlete_id", "analysis_type", "scope_key");



ALTER TABLE ONLY "public"."athletes"
    ADD CONSTRAINT "athletes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."athletes"
    ADD CONSTRAINT "athletes_strava_athlete_id_key" UNIQUE ("strava_athlete_id");



ALTER TABLE ONLY "public"."athletes"
    ADD CONSTRAINT "athletes_user_id_unique" UNIQUE ("user_id");



ALTER TABLE ONLY "public"."biometrics"
    ADD CONSTRAINT "biometrics_athlete_date_unique" UNIQUE ("athlete_id", "date");



ALTER TABLE ONLY "public"."biometrics"
    ADD CONSTRAINT "biometrics_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."coach_conversations"
    ADD CONSTRAINT "coach_conversations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."coach_memories"
    ADD CONSTRAINT "coach_memories_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."coach_messages"
    ADD CONSTRAINT "coach_messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."oauth_tokens"
    ADD CONSTRAINT "oauth_tokens_athlete_provider_unique" UNIQUE ("athlete_id", "provider");



ALTER TABLE ONLY "public"."oauth_tokens"
    ADD CONSTRAINT "oauth_tokens_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."push_tokens"
    ADD CONSTRAINT "push_tokens_athlete_id_token_key" UNIQUE ("athlete_id", "token");



ALTER TABLE ONLY "public"."push_tokens"
    ADD CONSTRAINT "push_tokens_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sleep_periods"
    ADD CONSTRAINT "sleep_periods_external_id_unique" UNIQUE ("source", "external_id");



ALTER TABLE ONLY "public"."sleep_periods"
    ADD CONSTRAINT "sleep_periods_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."training_plans"
    ADD CONSTRAINT "training_plans_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tss_history"
    ADD CONSTRAINT "tss_history_athlete_date_unique" UNIQUE ("athlete_id", "date");



ALTER TABLE ONLY "public"."tss_history"
    ADD CONSTRAINT "tss_history_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workouts"
    ADD CONSTRAINT "workouts_external_id_unique" UNIQUE ("source", "external_id");



ALTER TABLE ONLY "public"."workouts"
    ADD CONSTRAINT "workouts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."workouts"
    ADD CONSTRAINT "workouts_strava_activity_id_key" UNIQUE ("strava_activity_id");



CREATE INDEX "athlete_analyses_athlete_type_scope" ON "public"."athlete_analyses" USING "btree" ("athlete_id", "analysis_type", "scope_key");



CREATE INDEX "athlete_analyses_athlete_updated" ON "public"."athlete_analyses" USING "btree" ("athlete_id", "updated_at" DESC);



CREATE INDEX "biometrics_athlete_date" ON "public"."biometrics" USING "btree" ("athlete_id", "date" DESC);



CREATE INDEX "coach_conversations_athlete_updated" ON "public"."coach_conversations" USING "btree" ("athlete_id", "updated_at" DESC);



CREATE INDEX "coach_memories_athlete_idx" ON "public"."coach_memories" USING "btree" ("athlete_id", "created_at" DESC);



CREATE INDEX "coach_messages_athlete_created" ON "public"."coach_messages" USING "btree" ("athlete_id", "created_at" DESC);



CREATE INDEX "coach_messages_conversation_created" ON "public"."coach_messages" USING "btree" ("conversation_id", "created_at");



CREATE INDEX "idx_activity_laps_workout" ON "public"."activity_laps" USING "btree" ("workout_id", "lap_index");



CREATE INDEX "idx_activity_streams_workout" ON "public"."activity_streams" USING "btree" ("workout_id");



CREATE UNIQUE INDEX "idx_activity_streams_workout_unique" ON "public"."activity_streams" USING "btree" ("workout_id");



CREATE INDEX "idx_athlete_analyses_lookup" ON "public"."athlete_analyses" USING "btree" ("athlete_id", "analysis_type", "scope_key");



CREATE INDEX "idx_biometrics_athlete_date" ON "public"."biometrics" USING "btree" ("athlete_id", "date" DESC);



CREATE INDEX "idx_tss_history_athlete_date" ON "public"."tss_history" USING "btree" ("athlete_id", "date" DESC);



CREATE INDEX "idx_workouts_athlete_start" ON "public"."workouts" USING "btree" ("athlete_id", "started_at");



CREATE INDEX "idx_workouts_athlete_started" ON "public"."workouts" USING "btree" ("athlete_id", "started_at" DESC);



CREATE INDEX "idx_workouts_strava_id" ON "public"."workouts" USING "btree" ("strava_activity_id") WHERE ("strava_activity_id" IS NOT NULL);



CREATE INDEX "push_tokens_athlete_idx" ON "public"."push_tokens" USING "btree" ("athlete_id");



CREATE INDEX "sleep_periods_athlete_date" ON "public"."sleep_periods" USING "btree" ("athlete_id", "date" DESC);



CREATE INDEX "tss_history_athlete_date" ON "public"."tss_history" USING "btree" ("athlete_id", "date" DESC);



CREATE INDEX "workouts_athlete_started_at" ON "public"."workouts" USING "btree" ("athlete_id", "started_at" DESC);



ALTER TABLE ONLY "public"."activity_laps"
    ADD CONSTRAINT "activity_laps_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."activity_laps"
    ADD CONSTRAINT "activity_laps_workout_id_fkey" FOREIGN KEY ("workout_id") REFERENCES "public"."workouts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."activity_streams"
    ADD CONSTRAINT "activity_streams_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."activity_streams"
    ADD CONSTRAINT "activity_streams_workout_id_fkey" FOREIGN KEY ("workout_id") REFERENCES "public"."workouts"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."athlete_analyses"
    ADD CONSTRAINT "athlete_analyses_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."athletes"
    ADD CONSTRAINT "athletes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."biometrics"
    ADD CONSTRAINT "biometrics_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coach_conversations"
    ADD CONSTRAINT "coach_conversations_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coach_memories"
    ADD CONSTRAINT "coach_memories_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coach_messages"
    ADD CONSTRAINT "coach_messages_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."coach_messages"
    ADD CONSTRAINT "coach_messages_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."coach_conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."oauth_tokens"
    ADD CONSTRAINT "oauth_tokens_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."push_tokens"
    ADD CONSTRAINT "push_tokens_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sleep_periods"
    ADD CONSTRAINT "sleep_periods_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."training_plans"
    ADD CONSTRAINT "training_plans_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."training_plans"
    ADD CONSTRAINT "training_plans_completed_workout_id_fkey" FOREIGN KEY ("completed_workout_id") REFERENCES "public"."workouts"("id");



ALTER TABLE ONLY "public"."tss_history"
    ADD CONSTRAINT "tss_history_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."workouts"
    ADD CONSTRAINT "workouts_athlete_id_fkey" FOREIGN KEY ("athlete_id") REFERENCES "public"."athletes"("id") ON DELETE CASCADE;



CREATE POLICY "Athletes can view own TSS history" ON "public"."tss_history" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "tss_history"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own analyses" ON "public"."athlete_analyses" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "athlete_analyses"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own biometrics" ON "public"."biometrics" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "biometrics"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own conversations" ON "public"."coach_conversations" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "coach_conversations"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own laps" ON "public"."activity_laps" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM ("public"."workouts" "w"
     JOIN "public"."athletes" "a" ON (("a"."id" = "w"."athlete_id")))
  WHERE (("w"."id" = "activity_laps"."workout_id") AND ("a"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own memories" ON "public"."coach_memories" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "coach_memories"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own messages" ON "public"."coach_messages" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM ("public"."coach_conversations" "cc"
     JOIN "public"."athletes" "a" ON (("a"."id" = "cc"."athlete_id")))
  WHERE (("cc"."id" = "coach_messages"."conversation_id") AND ("a"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own oauth tokens" ON "public"."oauth_tokens" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "oauth_tokens"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own profile" ON "public"."athletes" FOR SELECT TO "authenticated" USING (("user_id" = "auth"."uid"()));



CREATE POLICY "Athletes can view own push tokens" ON "public"."push_tokens" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "push_tokens"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own sleep" ON "public"."sleep_periods" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "sleep_periods"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own streams" ON "public"."activity_streams" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM ("public"."workouts" "w"
     JOIN "public"."athletes" "a" ON (("a"."id" = "w"."athlete_id")))
  WHERE (("w"."id" = "activity_streams"."workout_id") AND ("a"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own training plans" ON "public"."training_plans" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "training_plans"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes can view own workouts" ON "public"."workouts" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."athletes"
  WHERE (("athletes"."id" = "workouts"."athlete_id") AND ("athletes"."user_id" = "auth"."uid"())))));



CREATE POLICY "Athletes manage own push tokens" ON "public"."push_tokens" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"())))) WITH CHECK (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."activity_laps" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."activity_streams" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."athlete_analyses" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "athlete_analyses_athlete_access" ON "public"."athlete_analyses" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"())))) WITH CHECK (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."athletes" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "athletes_self_access" ON "public"."athletes" USING (("user_id" = "auth"."uid"()));



ALTER TABLE "public"."biometrics" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "biometrics_athlete_access" ON "public"."biometrics" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."coach_conversations" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "coach_conversations_athlete_access" ON "public"."coach_conversations" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"())))) WITH CHECK (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."coach_memories" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "coach_memories_athlete_access" ON "public"."coach_memories" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"())))) WITH CHECK (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."coach_messages" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "coach_messages_athlete_access" ON "public"."coach_messages" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"())))) WITH CHECK (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



CREATE POLICY "laps_self_access" ON "public"."activity_laps" USING (("athlete_id" = ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."oauth_tokens" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "oauth_tokens_athlete_access" ON "public"."oauth_tokens" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."push_tokens" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."sleep_periods" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "sleep_periods_athlete_access" ON "public"."sleep_periods" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



CREATE POLICY "streams_self_access" ON "public"."activity_streams" USING (("athlete_id" = ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."training_plans" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "training_plans_athlete_access" ON "public"."training_plans" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."tss_history" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "tss_history_athlete_access" ON "public"."tss_history" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));



ALTER TABLE "public"."workouts" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "workouts_athlete_access" ON "public"."workouts" USING (("athlete_id" IN ( SELECT "athletes"."id"
   FROM "public"."athletes"
  WHERE ("athletes"."user_id" = "auth"."uid"()))));





ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";












































































































































































































































































































































































































































































































GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "service_role";



GRANT ALL ON FUNCTION "public"."match_coach_memories"("athlete_id" "uuid", "query_embedding" double precision[], "match_threshold" double precision, "match_count" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."match_coach_memories"("athlete_id" "uuid", "query_embedding" double precision[], "match_threshold" double precision, "match_count" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."match_coach_memories"("athlete_id" "uuid", "query_embedding" double precision[], "match_threshold" double precision, "match_count" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "anon";
GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."rls_auto_enable"() TO "service_role";






























GRANT ALL ON TABLE "public"."activity_laps" TO "anon";
GRANT ALL ON TABLE "public"."activity_laps" TO "authenticated";
GRANT ALL ON TABLE "public"."activity_laps" TO "service_role";



GRANT ALL ON TABLE "public"."activity_streams" TO "anon";
GRANT ALL ON TABLE "public"."activity_streams" TO "authenticated";
GRANT ALL ON TABLE "public"."activity_streams" TO "service_role";



GRANT ALL ON TABLE "public"."athlete_analyses" TO "anon";
GRANT ALL ON TABLE "public"."athlete_analyses" TO "authenticated";
GRANT ALL ON TABLE "public"."athlete_analyses" TO "service_role";



GRANT ALL ON TABLE "public"."athletes" TO "anon";
GRANT ALL ON TABLE "public"."athletes" TO "authenticated";
GRANT ALL ON TABLE "public"."athletes" TO "service_role";



GRANT ALL ON TABLE "public"."biometrics" TO "anon";
GRANT ALL ON TABLE "public"."biometrics" TO "authenticated";
GRANT ALL ON TABLE "public"."biometrics" TO "service_role";



GRANT ALL ON TABLE "public"."coach_conversations" TO "anon";
GRANT ALL ON TABLE "public"."coach_conversations" TO "authenticated";
GRANT ALL ON TABLE "public"."coach_conversations" TO "service_role";



GRANT ALL ON TABLE "public"."coach_memories" TO "anon";
GRANT ALL ON TABLE "public"."coach_memories" TO "authenticated";
GRANT ALL ON TABLE "public"."coach_memories" TO "service_role";



GRANT ALL ON TABLE "public"."coach_messages" TO "anon";
GRANT ALL ON TABLE "public"."coach_messages" TO "authenticated";
GRANT ALL ON TABLE "public"."coach_messages" TO "service_role";



GRANT ALL ON TABLE "public"."oauth_tokens" TO "anon";
GRANT ALL ON TABLE "public"."oauth_tokens" TO "authenticated";
GRANT ALL ON TABLE "public"."oauth_tokens" TO "service_role";



GRANT ALL ON TABLE "public"."push_tokens" TO "anon";
GRANT ALL ON TABLE "public"."push_tokens" TO "authenticated";
GRANT ALL ON TABLE "public"."push_tokens" TO "service_role";



GRANT ALL ON TABLE "public"."sleep_periods" TO "anon";
GRANT ALL ON TABLE "public"."sleep_periods" TO "authenticated";
GRANT ALL ON TABLE "public"."sleep_periods" TO "service_role";



GRANT ALL ON TABLE "public"."training_plans" TO "anon";
GRANT ALL ON TABLE "public"."training_plans" TO "authenticated";
GRANT ALL ON TABLE "public"."training_plans" TO "service_role";



GRANT ALL ON TABLE "public"."tss_history" TO "anon";
GRANT ALL ON TABLE "public"."tss_history" TO "authenticated";
GRANT ALL ON TABLE "public"."tss_history" TO "service_role";



GRANT ALL ON TABLE "public"."workouts" TO "anon";
GRANT ALL ON TABLE "public"."workouts" TO "authenticated";
GRANT ALL ON TABLE "public"."workouts" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";



































