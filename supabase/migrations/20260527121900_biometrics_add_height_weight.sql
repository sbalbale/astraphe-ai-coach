-- Add body metrics to biometrics for time-series tracking.
-- WHOOP/Garmin can emit these over time; store alongside daily biometrics.

alter table public.biometrics
  add column if not exists weight_kg numeric(5,2),
  add column if not exists height_cm numeric(5,1);

