-- Rename workout sport value: rowing -> row
-- Keep as TEXT + CHECK constraint (no enum type in use).

-- 1) Temporarily allow both values so we can update existing rows safely.
ALTER TABLE public.workouts
DROP CONSTRAINT IF EXISTS workouts_sport_check;

ALTER TABLE public.workouts
ADD CONSTRAINT workouts_sport_check
CHECK (sport IN ('run','bike','swim','strength','rowing','row','other'));

-- 2) Update existing rows.
UPDATE public.workouts
SET sport = 'row'
WHERE sport = 'rowing';

-- 3) Enforce final allowed set (row, not rowing).
ALTER TABLE public.workouts
DROP CONSTRAINT IF EXISTS workouts_sport_check;

ALTER TABLE public.workouts
ADD CONSTRAINT workouts_sport_check
CHECK (sport IN ('run','bike','swim','strength','row','other'));

