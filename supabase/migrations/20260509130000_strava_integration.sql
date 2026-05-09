-- Strava integration: workouts + athletes extensions, streams/laps tables, indexes, RLS.
-- Non-destructive additions; workouts.source CHECK is widened via constraint replace only.

-- 1. Workouts — Strava and source metadata
ALTER TABLE workouts
  ADD COLUMN IF NOT EXISTS strava_activity_id BIGINT UNIQUE,
  ADD COLUMN IF NOT EXISTS strava_streams_fetched BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS primary_source TEXT DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS source_ids JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS raw_strava_payload JSONB;

-- 2. Workouts — intervals / splits (canonical 500m + raw Strava split arrays)
ALTER TABLE workouts
  ADD COLUMN IF NOT EXISTS intervals JSONB,
  ADD COLUMN IF NOT EXISTS intervals_source TEXT,
  ADD COLUMN IF NOT EXISTS splits_metric JSONB,
  ADD COLUMN IF NOT EXISTS splits_standard JSONB;

-- 3. Workouts.source — allow Strava ingestion
ALTER TABLE workouts DROP CONSTRAINT IF EXISTS workouts_source_check;

ALTER TABLE workouts ADD CONSTRAINT workouts_source_check
  CHECK (
    source IN ('garmin', 'whoop', 'healthkit', 'manual', 'strava')
  );

-- 4. Athletes — LTHR mirror + Strava linkage (lthr aliases threshold_hr, read-only generated)
ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS lthr SMALLINT GENERATED ALWAYS AS (threshold_hr) STORED;

ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS hr_zone_method TEXT DEFAULT 'lthr';

ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS strava_athlete_id BIGINT UNIQUE;

-- 5. activity_streams (heavy payload isolated from workouts)
CREATE TABLE IF NOT EXISTS activity_streams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workout_id UUID NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
  athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  time_series JSONB NOT NULL,
  resolution_seconds INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE activity_streams ENABLE ROW LEVEL SECURITY;

CREATE POLICY "streams_self_access" ON activity_streams
  FOR ALL USING (
    athlete_id = (SELECT id FROM athletes WHERE user_id = auth.uid())
  );

-- 6. activity_laps
CREATE TABLE IF NOT EXISTS activity_laps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workout_id UUID NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
  athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  lap_index INT,
  start_index INT,
  end_index INT,
  elapsed_time INT,
  moving_time INT,
  distance FLOAT,
  average_heartrate FLOAT,
  max_heartrate FLOAT,
  average_watts FLOAT,
  average_cadence FLOAT,
  average_speed FLOAT,
  total_elevation_gain FLOAT,
  raw_lap JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE activity_laps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "laps_self_access" ON activity_laps
  FOR ALL USING (
    athlete_id = (SELECT id FROM athletes WHERE user_id = auth.uid())
  );

-- 7. Indexes — dedupe + lookups
CREATE INDEX IF NOT EXISTS idx_workouts_athlete_start
  ON workouts (athlete_id, started_at);

CREATE INDEX IF NOT EXISTS idx_workouts_strava_id
  ON workouts (strava_activity_id)
  WHERE strava_activity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_streams_workout
  ON activity_streams (workout_id);

CREATE INDEX IF NOT EXISTS idx_activity_laps_workout
  ON activity_laps (workout_id, lap_index);
