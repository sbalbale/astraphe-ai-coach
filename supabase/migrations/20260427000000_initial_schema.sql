-- Enable pgcrypto for UUIDs
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. athletes
CREATE TABLE athletes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name    TEXT NOT NULL,
  city            TEXT,
  country_code    CHAR(2),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  date_of_birth   DATE,
  weight_kg       NUMERIC(5,2),
  height_cm       NUMERIC(5,1),
  max_hr          SMALLINT,
  resting_hr      SMALLINT,
  ftp_watts       SMALLINT,
  threshold_hr    SMALLINT,
  threshold_pace  NUMERIC(5,2),
  vo2max_est      NUMERIC(4,1),
  sport_focus     TEXT[] DEFAULT '{"run","bike"}',
  weekly_tss_target SMALLINT DEFAULT 400,
  CONSTRAINT athletes_user_id_unique UNIQUE (user_id)
);
ALTER TABLE athletes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "athletes_self_access" ON athletes
  FOR ALL USING (user_id = auth.uid());

-- 2. workouts
CREATE TABLE workouts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  source          TEXT NOT NULL CHECK (source IN ('garmin','whoop','healthkit','manual')),
  external_id     TEXT,
  sport           TEXT NOT NULL CHECK (sport IN ('run','bike','swim','strength','other')),
  title           TEXT,
  started_at      TIMESTAMPTZ NOT NULL,
  ended_at        TIMESTAMPTZ NOT NULL,
  distance_m      NUMERIC(10,2),
  elevation_gain_m NUMERIC(8,2),
  avg_hr          SMALLINT,
  max_hr          SMALLINT,
  avg_power_w     SMALLINT,
  norm_power_w    SMALLINT,
  avg_pace_sec_km SMALLINT,
  tss             NUMERIC(6,2),
  if_value        NUMERIC(4,3),
  fit_file_url    TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT workouts_external_id_unique UNIQUE (source, external_id)
);
CREATE INDEX workouts_athlete_started_at ON workouts (athlete_id, started_at DESC);
ALTER TABLE workouts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workouts_athlete_access" ON workouts
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 3. biometrics
CREATE TABLE biometrics (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  date            DATE NOT NULL,
  hrv_rmssd       NUMERIC(6,2),
  hrv_source      TEXT CHECK (hrv_source IN ('whoop','garmin','healthkit')),
  resting_hr      SMALLINT,
  sleep_duration_min   SMALLINT,
  sleep_score          SMALLINT,
  sleep_deep_pct       NUMERIC(4,1),
  sleep_rem_pct        NUMERIC(4,1),
  sleep_light_pct      NUMERIC(4,1),
  sleep_awake_pct      NUMERIC(4,1),
  sleep_bedtime        TIMESTAMPTZ,
  sleep_wakeup         TIMESTAMPTZ,
  skin_temp_deviation  NUMERIC(4,2),
  spo2_pct             NUMERIC(4,1),
  recovery_score       SMALLINT,
  CONSTRAINT biometrics_athlete_date_unique UNIQUE (athlete_id, date)
);
CREATE INDEX biometrics_athlete_date ON biometrics (athlete_id, date DESC);
ALTER TABLE biometrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "biometrics_athlete_access" ON biometrics
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 4. tss_history
CREATE TABLE tss_history (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  date            DATE NOT NULL,
  daily_tss       NUMERIC(7,2) NOT NULL DEFAULT 0,
  workout_ids     UUID[],
  ctl             NUMERIC(6,2),
  atl             NUMERIC(6,2),
  tsb             NUMERIC(7,2),
  CONSTRAINT tss_history_athlete_date_unique UNIQUE (athlete_id, date)
);
CREATE INDEX tss_history_athlete_date ON tss_history (athlete_id, date DESC);
ALTER TABLE tss_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tss_history_athlete_access" ON tss_history
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 5. training_plans
CREATE TABLE training_plans (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  planned_date    DATE NOT NULL,
  sport           TEXT NOT NULL,
  title           TEXT NOT NULL,
  description     TEXT,
  duration_min    SMALLINT,
  target_tss      SMALLINT,
  target_zones    JSONB,
  status          TEXT NOT NULL DEFAULT 'planned'
                  CHECK (status IN ('planned','done','skipped','modified')),
  completed_workout_id UUID REFERENCES workouts(id),
  generated_by    TEXT DEFAULT 'astraphe_ai',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE training_plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY "training_plans_athlete_access" ON training_plans
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- ==========================================
-- AUTO-CREATE ATHLETE ON SIGNUP TRIGGER
-- ==========================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.athletes (user_id, display_name)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1))
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
