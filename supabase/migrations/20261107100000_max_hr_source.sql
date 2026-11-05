-- Where athletes.max_hr came from: entered by the athlete ('manual') or estimated by the app
-- ('estimated': the higher of the age estimate and the highest recorded heart rate). An
-- estimated value can be raised by a later, higher recorded HR; a manual one is never changed.
ALTER TABLE public.athletes
  ADD COLUMN IF NOT EXISTS max_hr_source text
    CHECK (max_hr_source IS NULL OR max_hr_source IN ('manual', 'estimated'));

-- Existing max HR values were entered by the athlete or came from a provider: keep them as is.
UPDATE public.athletes SET max_hr_source = 'manual' WHERE max_hr IS NOT NULL AND max_hr_source IS NULL;
