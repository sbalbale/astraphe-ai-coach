-- Garmin's skin temperature is a deviation from the athlete's own baseline
-- (Garmin Connect's "Avg Skin Temp Change"), not an absolute reading like
-- WHOOP's skin_temp (see whoop.py's skin_temp_celsius, ~33-35C). Mixing the
-- two in one column would corrupt the mobile recovery page's baseline/z-score
-- math, which treats skin_temp as an absolute temperature. Separate column.

ALTER TABLE biometrics
  ADD COLUMN IF NOT EXISTS skin_temp_deviation_c NUMERIC(4,2);
