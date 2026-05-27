-- workouts_athlete_started_at already covers athlete_id + started_at DESC list queries.
-- idx_workouts_athlete_start is a redundant ASC variant left from Strava integration.
DROP INDEX IF EXISTS public.idx_workouts_athlete_start;

ANALYZE public.workouts;
