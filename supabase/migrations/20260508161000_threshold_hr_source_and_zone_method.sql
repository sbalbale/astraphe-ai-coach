-- Tiered HR zones: source of threshold HR + informational zone_method
ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS threshold_hr_source TEXT
    CHECK (threshold_hr_source IS NULL OR threshold_hr_source IN ('manual', 'estimated'));

-- One-time backfill: legacy rows with threshold set but no source → estimated
UPDATE athletes
SET threshold_hr_source = 'estimated'
WHERE threshold_hr IS NOT NULL
  AND threshold_hr_source IS NULL;

-- Informational only (matches app.services.hr_zones.compute_hr_zones tier priority)
ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS zone_method TEXT
    GENERATED ALWAYS AS (
      CASE
        WHEN threshold_hr IS NOT NULL AND threshold_hr > 0 AND threshold_hr_source = 'manual' THEN 'lthr'
        WHEN max_hr IS NOT NULL AND max_hr > 0
          AND resting_hr IS NOT NULL AND resting_hr > 0
          AND max_hr > resting_hr THEN 'hrr'
        WHEN max_hr IS NOT NULL AND max_hr > 0 THEN 'max_hr'
        ELSE NULL
      END
    ) STORED;

COMMENT ON COLUMN athletes.threshold_hr_source IS 'manual = user-entered LTHR; estimated = pipeline-derived';
COMMENT ON COLUMN athletes.zone_method IS 'Derived tier used for HR zones display (lthr|hrr|max_hr)';
