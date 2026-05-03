-- Athlete timezone settings

ALTER TABLE public.athletes
ADD COLUMN IF NOT EXISTS timezone_offset_min INTEGER NOT NULL DEFAULT 0;

