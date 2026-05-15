-- One stream bundle per workout (upsert / hydrate rely on this).
CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_streams_workout_unique
  ON activity_streams (workout_id);
