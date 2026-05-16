-- Enforce allowed tokens for athletes.hr_zone_method (see backend canonicalization + PATCH/PUT).
ALTER TABLE public.athletes
  ADD CONSTRAINT hr_zone_method_valid
  CHECK (hr_zone_method IS NULL OR hr_zone_method IN ('lthr', 'hrr', 'max_hr'));
