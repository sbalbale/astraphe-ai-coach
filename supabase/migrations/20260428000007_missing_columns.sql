-- Add missing columns to biometrics table that are required by the backend logic
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS day_strain NUMERIC(4,1);
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS sleep_need_min SMALLINT;
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS sleep_debt_min SMALLINT;
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astraphe_readiness_score SMALLINT;
ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS astraphe_strain_score SMALLINT;

ALTER TABLE workouts ADD COLUMN IF NOT EXISTS hr_zone_0_pct SMALLINT;
ALTER TABLE workouts ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;
