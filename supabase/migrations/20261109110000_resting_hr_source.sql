-- Where athletes.resting_hr came from: 'measured' (the 42-day mean of the wearable's
-- daily resting HR, kept up to date as days sync) or 'manual' (entered by the athlete,
-- never replaced). Until now every synced day overwrote it with the measured value, so
-- existing rows are 'measured'; the athlete can pin their own from Training settings.
ALTER TABLE public.athletes
  ADD COLUMN IF NOT EXISTS resting_hr_source text
    CHECK (resting_hr_source IS NULL OR resting_hr_source IN ('manual', 'measured'));

UPDATE public.athletes SET resting_hr_source = 'measured'
WHERE resting_hr IS NOT NULL AND resting_hr_source IS NULL;
