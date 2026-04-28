-- Add Astrape-specific scoring columns to biometrics and workouts
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astrape_sleep_score SMALLINT;
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astrape_recovery_score SMALLINT;
ALTER TABLE workouts ADD COLUMN IF NOT EXISTS astrape_strain_score SMALLINT;
