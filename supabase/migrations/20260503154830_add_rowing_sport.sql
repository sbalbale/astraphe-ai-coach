-- Allow storing rowing workouts

ALTER TABLE public.workouts
DROP CONSTRAINT IF EXISTS workouts_sport_check;

ALTER TABLE public.workouts
ADD CONSTRAINT workouts_sport_check
CHECK (sport IN ('run','bike','swim','strength','rowing','other'));

