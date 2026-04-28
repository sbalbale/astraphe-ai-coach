-- Add HR zone percentage columns to workouts table
ALTER TABLE workouts
ADD COLUMN IF NOT EXISTS hr_zone_1_pct SMALLINT,
ADD COLUMN IF NOT EXISTS hr_zone_2_pct SMALLINT,
ADD COLUMN IF NOT EXISTS hr_zone_3_pct SMALLINT,
ADD COLUMN IF NOT EXISTS hr_zone_4_pct SMALLINT,
ADD COLUMN IF NOT EXISTS hr_zone_5_pct SMALLINT;

COMMENT ON COLUMN workouts.hr_zone_1_pct IS 'Percentage of time spent in heart rate zone 1';
COMMENT ON COLUMN workouts.hr_zone_2_pct IS 'Percentage of time spent in heart rate zone 2';
COMMENT ON COLUMN workouts.hr_zone_3_pct IS 'Percentage of time spent in heart rate zone 3';
COMMENT ON COLUMN workouts.hr_zone_4_pct IS 'Percentage of time spent in heart rate zone 4';
COMMENT ON COLUMN workouts.hr_zone_5_pct IS 'Percentage of time spent in heart rate zone 5';
