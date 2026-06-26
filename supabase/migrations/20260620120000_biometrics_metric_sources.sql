-- Track provider/source provenance per biometrics metric.
-- This lets ingestion keep the highest-quality source per field while still filling gaps.

ALTER TABLE public.biometrics
  ADD COLUMN IF NOT EXISTS metric_sources JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.biometrics.metric_sources IS
  'Per-field provenance for biometrics merges, e.g. sleep_duration_min=whoop, sleep_score=astraphe_backup.';
