-- Allow Intervals.icu as a server-side ingestion provider.
-- This only widens existing CHECK constraints; no data is rewritten.

ALTER TABLE public.workouts DROP CONSTRAINT IF EXISTS workouts_source_check;

ALTER TABLE public.workouts ADD CONSTRAINT workouts_source_check
  CHECK (
    source IN ('garmin', 'whoop', 'healthkit', 'manual', 'strava', 'intervals_icu')
  );

ALTER TABLE public.biometrics DROP CONSTRAINT IF EXISTS biometrics_hrv_source_check;

ALTER TABLE public.biometrics ADD CONSTRAINT biometrics_hrv_source_check
  CHECK (
    hrv_source IS NULL
    OR hrv_source IN ('whoop', 'garmin', 'healthkit', 'intervals_icu')
  );
