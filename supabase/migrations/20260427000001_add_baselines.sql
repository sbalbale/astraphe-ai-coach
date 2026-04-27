-- Add baseline metrics for coaching algorithms
ALTER TABLE athletes 
ADD COLUMN IF NOT EXISTS hrv_baseline NUMERIC(6,2),
ADD COLUMN IF NOT EXISTS rhr_baseline SMALLINT;
