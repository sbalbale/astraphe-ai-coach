-- Store only: run, bike, swim, strength, row, mobility, other.
-- Map Strava-style / canonical names into DB CHECK values, then enforce.

UPDATE public.workouts
SET sport = CASE lower(sport)
  WHEN 'cycling' THEN 'bike'
  WHEN 'rowing' THEN 'row'
  WHEN 'walk' THEN 'other'
  WHEN 'hike' THEN 'other'
  ELSE sport
END
WHERE sport IS NOT NULL
  AND lower(sport) IN ('cycling', 'rowing', 'walk', 'hike');

UPDATE public.workouts
SET sport = 'other'
WHERE sport IS NOT NULL
  AND lower(sport) NOT IN ('run', 'bike', 'swim', 'strength', 'row', 'mobility', 'other');

ALTER TABLE public.workouts
  DROP CONSTRAINT IF EXISTS workouts_sport_check;

ALTER TABLE public.workouts
  ADD CONSTRAINT workouts_sport_check
  CHECK (sport IN ('run', 'bike', 'swim', 'strength', 'row', 'mobility', 'other'));
