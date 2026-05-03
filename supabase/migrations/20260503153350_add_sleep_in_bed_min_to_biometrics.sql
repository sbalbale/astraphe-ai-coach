-- Add missing sleep aggregation column used by backend processing

ALTER TABLE public.biometrics
ADD COLUMN IF NOT EXISTS sleep_in_bed_min SMALLINT;

