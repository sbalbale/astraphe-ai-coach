-- 20260429000000_unify_score_names.sql
-- This migration standardizes the column names for Astraphe proprietary scores.

-- 1. Biometrics Table
-- Rename existing Astraphe columns if they exist
DO $$ 
BEGIN
    -- strain_score
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='strain_score') THEN
        -- already standardized
        NULL;
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astraphe_strain_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astraphe_strain_score TO strain_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN strain_score SMALLINT;
    END IF;

    -- readiness_score
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='readiness_score') THEN
        NULL;
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astraphe_readiness_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astraphe_readiness_score TO readiness_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN readiness_score SMALLINT;
    END IF;

    -- sleep_score (Legacy sleep_score moved to source_sleep_score)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='source_sleep_score')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='sleep_score')
    THEN
        ALTER TABLE biometrics RENAME COLUMN sleep_score TO source_sleep_score;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='sleep_score') THEN
        NULL;
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astraphe_sleep_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astraphe_sleep_score TO sleep_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN sleep_score SMALLINT;
    END IF;

    -- recovery_score (Legacy recovery_score moved to source_recovery_score)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='source_recovery_score')
       AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='recovery_score')
    THEN
        ALTER TABLE biometrics RENAME COLUMN recovery_score TO source_recovery_score;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='recovery_score') THEN
        NULL;
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='biometrics' AND column_name='astraphe_recovery_score') THEN
        ALTER TABLE biometrics RENAME COLUMN astraphe_recovery_score TO recovery_score;
    ELSE
        ALTER TABLE biometrics ADD COLUMN recovery_score SMALLINT;
    END IF;

END $$;

-- 2. Workouts Table
-- Rename astraphe_strain_score to strain_score
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='workouts' AND column_name='strain_score') THEN
        NULL;
    ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='workouts' AND column_name='astraphe_strain_score') THEN
        ALTER TABLE workouts RENAME COLUMN astraphe_strain_score TO strain_score;
    ELSE
        ALTER TABLE workouts ADD COLUMN strain_score SMALLINT;
    END IF;
END $$;
