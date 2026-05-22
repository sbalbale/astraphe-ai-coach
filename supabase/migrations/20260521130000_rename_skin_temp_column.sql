-- Rename skin_temp_deviation to skin_temp as it stores absolute Celsius, not deviation.
ALTER TABLE public.biometrics 
RENAME COLUMN skin_temp_deviation TO skin_temp;
