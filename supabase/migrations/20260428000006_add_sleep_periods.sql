-- Migration: Add sleep_periods table for individual nap tracking
-- Path: supabase/migrations/20260428000006_add_sleep_periods.sql

CREATE TABLE IF NOT EXISTS sleep_periods (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  date            DATE NOT NULL, -- The biological day this sleep belongs to
  started_at      TIMESTAMPTZ NOT NULL,
  ended_at        TIMESTAMPTZ NOT NULL,
  duration_min    SMALLINT NOT NULL,
  score           SMALLINT,
  deep_pct        NUMERIC(4,1),
  rem_pct         NUMERIC(4,1),
  light_pct       NUMERIC(4,1),
  awake_pct       NUMERIC(4,1),
  is_nap          BOOLEAN DEFAULT FALSE,
  source          TEXT NOT NULL,
  external_id     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT sleep_periods_external_id_unique UNIQUE (source, external_id)
);

-- Index for efficient lookup by athlete and date
CREATE INDEX IF NOT EXISTS sleep_periods_athlete_date ON sleep_periods (athlete_id, date DESC);

-- Enable RLS
ALTER TABLE sleep_periods ENABLE ROW LEVEL SECURITY;

-- Policy: Athletes can see their own sleep periods
CREATE POLICY "sleep_periods_athlete_access" ON sleep_periods
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));
