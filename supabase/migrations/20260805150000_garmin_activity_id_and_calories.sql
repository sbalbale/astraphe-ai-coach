-- Garmin fast-path identity + calories on workouts.
-- Mirrors strava_activity_id (20260509130000). elevation_gain_m already exists.

ALTER TABLE workouts
  ADD COLUMN IF NOT EXISTS garmin_activity_id BIGINT UNIQUE,
  ADD COLUMN IF NOT EXISTS calories NUMERIC(8,1);

CREATE INDEX IF NOT EXISTS idx_workouts_garmin_id
  ON workouts (garmin_activity_id)
  WHERE garmin_activity_id IS NOT NULL;
