-- Add Astraphe-specific scoring columns to biometrics and workouts
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astraphe_sleep_score SMALLINT;
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astraphe_recovery_score SMALLINT;
ALTER TABLE workouts ADD COLUMN IF NOT EXISTS astraphe_strain_score SMALLINT;
