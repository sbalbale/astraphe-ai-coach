-- Drop legacy astraphe_* score columns no longer used by the API.
-- Canonical columns: sleep_score, recovery_score, readiness_score, strain_score.
-- Idempotent: safe on dev (columns already renamed/absent) and prod (may still have astraphe_*).

-- 1. Ensure canonical columns exist (matches 20260429000000_unify_score_names.sql)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'strain_score'
    ) THEN
        ALTER TABLE biometrics ADD COLUMN strain_score SMALLINT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'readiness_score'
    ) THEN
        ALTER TABLE biometrics ADD COLUMN readiness_score SMALLINT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'source_sleep_score'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'sleep_score'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_sleep_score'
    ) THEN
        ALTER TABLE biometrics RENAME COLUMN sleep_score TO source_sleep_score;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'sleep_score'
    ) THEN
        ALTER TABLE biometrics ADD COLUMN sleep_score SMALLINT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'source_recovery_score'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'recovery_score'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_recovery_score'
    ) THEN
        ALTER TABLE biometrics RENAME COLUMN recovery_score TO source_recovery_score;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'recovery_score'
    ) THEN
        ALTER TABLE biometrics ADD COLUMN recovery_score SMALLINT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'workouts' AND column_name = 'strain_score'
    ) THEN
        ALTER TABLE workouts ADD COLUMN strain_score SMALLINT;
    END IF;
END $$;

-- 2. Backfill canonical columns from legacy astraphe_* where both columns coexist
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_sleep_score'
    ) THEN
        EXECUTE $sql$
            UPDATE biometrics
            SET sleep_score = astraphe_sleep_score
            WHERE sleep_score IS NULL
              AND astraphe_sleep_score IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_recovery_score'
    ) THEN
        EXECUTE $sql$
            UPDATE biometrics
            SET recovery_score = astraphe_recovery_score
            WHERE recovery_score IS NULL
              AND astraphe_recovery_score IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_readiness_score'
    ) THEN
        EXECUTE $sql$
            UPDATE biometrics
            SET readiness_score = astraphe_readiness_score
            WHERE readiness_score IS NULL
              AND astraphe_readiness_score IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'biometrics' AND column_name = 'astraphe_strain_score'
    ) THEN
        EXECUTE $sql$
            UPDATE biometrics
            SET strain_score = astraphe_strain_score
            WHERE strain_score IS NULL
              AND astraphe_strain_score IS NOT NULL
        $sql$;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'workouts' AND column_name = 'astraphe_strain_score'
    ) THEN
        EXECUTE $sql$
            UPDATE workouts
            SET strain_score = astraphe_strain_score
            WHERE strain_score IS NULL
              AND astraphe_strain_score IS NOT NULL
        $sql$;
    END IF;
END $$;

-- 3. Drop unused legacy columns
ALTER TABLE biometrics DROP COLUMN IF EXISTS astraphe_sleep_score;
ALTER TABLE biometrics DROP COLUMN IF EXISTS astraphe_recovery_score;
ALTER TABLE biometrics DROP COLUMN IF EXISTS astraphe_readiness_score;
ALTER TABLE biometrics DROP COLUMN IF EXISTS astraphe_strain_score;

ALTER TABLE workouts DROP COLUMN IF EXISTS astraphe_strain_score;
