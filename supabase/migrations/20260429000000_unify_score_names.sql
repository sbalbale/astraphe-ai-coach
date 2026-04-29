-- 20260429000000_unify_score_names.sql
-- This migration standardizes the column names for Astrape proprietary scores.

-- 1. Biometrics Table
-- Rename existing Astrape columns if they exist
DO $$ 
BEGIN
    -- strain_score
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astrape_strain_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astrape_strain_score TO strain_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS strain_score SMALLINT;
    END IF;

    -- readiness_score
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astrape_readiness_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astrape_readiness_score TO readiness_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS readiness_score SMALLINT;
    END IF;

    -- sleep_score (Legacy sleep_score moved to source_sleep_score)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='source_sleep_score') THEN
        ALTER TABLE biometrics RENAME COLUMN sleep_score TO source_sleep_score;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astrape_sleep_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astrape_sleep_score TO sleep_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS sleep_score SMALLINT;
    END IF;

    -- recovery_score (Legacy recovery_score moved to source_recovery_score)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='source_recovery_score') THEN
        ALTER TABLE biometrics RENAME COLUMN recovery_score TO source_recovery_score;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astrape_recovery_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astrape_recovery_score TO recovery_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN IF NOT EXISTS recovery_score SMALLINT;
    END IF;

END $$;

-- 2. Workouts Table
-- Rename astrape_strain_score to strain_score
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='workouts' AND column_name='astrape_strain_score') THEN
        ALTER TABLE workouts RENAME COLUMN astrape_strain_score TO strain_score;
    ELSE
        ALTER TABLE workouts ADD COLUMN IF NOT EXISTS strain_score SMALLINT;
    END IF;
END $$;
