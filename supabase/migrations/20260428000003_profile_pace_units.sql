-- Store threshold pace in the same format the mobile UI uses ("mm:ss")
-- and persist measurement units.

ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS measurement_units TEXT NOT NULL DEFAULT 'metric';

-- Convert existing numeric minutes-per-km to a display string if needed.
-- Example: 4.50 -> "4:30"
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'athletes'
      AND column_name = 'threshold_pace'
      AND data_type <> 'text'
  ) THEN
    ALTER TABLE athletes
      ALTER COLUMN threshold_pace TYPE TEXT
      USING (
        CASE
          WHEN threshold_pace IS NULL THEN NULL
          ELSE
            (floor(threshold_pace)::int)::text || ':' ||
            lpad(round((threshold_pace - floor(threshold_pace)) * 60)::int::text, 2, '0')
        END
      );
  END IF;
END $$;

