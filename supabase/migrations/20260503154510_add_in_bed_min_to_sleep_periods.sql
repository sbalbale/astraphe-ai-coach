-- Add derived in-bed duration for sleep sessions

ALTER TABLE public.sleep_periods
ADD COLUMN IF NOT EXISTS in_bed_min SMALLINT;

