-- Linking recorded workouts to planned sessions.
-- Additive (new columns have defaults), so the API running before this deploy keeps working.

-- ---------------------------------------------------------------------------------------
-- 1) Planned session ↔ recorded workout
-- ---------------------------------------------------------------------------------------
-- completed_workout_id already exists (unused until now). A session is:
--   done + linked       status='done' and completed_workout_id set
--   done, no workout    status='done' and completed_workout_id null
--   not done            status in ('planned','modified')
ALTER TABLE public.training_plans
  ADD COLUMN IF NOT EXISTS link_source text,
  -- Workouts the athlete said "not this one" to, or unlinked after an auto-match:
  -- never auto-matched to this session again.
  ADD COLUMN IF NOT EXISTS dismissed_workout_ids uuid[] NOT NULL DEFAULT '{}';

ALTER TABLE public.training_plans DROP CONSTRAINT IF EXISTS training_plans_link_source_check;
ALTER TABLE public.training_plans
  ADD CONSTRAINT training_plans_link_source_check CHECK (link_source IS NULL OR link_source IN ('auto', 'manual'));

-- One recorded workout completes at most one session.
CREATE UNIQUE INDEX IF NOT EXISTS training_plans_completed_workout_unique
  ON public.training_plans (completed_workout_id)
  WHERE completed_workout_id IS NOT NULL;

-- The FK had no delete rule, so deleting a linked workout failed. Deleting it now
-- un-completes the session (trigger below) and clears the link.
ALTER TABLE public.training_plans DROP CONSTRAINT IF EXISTS training_plans_completed_workout_id_fkey;
ALTER TABLE public.training_plans
  ADD CONSTRAINT training_plans_completed_workout_id_fkey
  FOREIGN KEY (completed_workout_id) REFERENCES public.workouts(id) ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION public.unlink_plans_for_deleted_workout()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
  UPDATE public.training_plans
     SET status = 'planned', link_source = NULL, completed_workout_id = NULL
   WHERE completed_workout_id = OLD.id;
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS workouts_unlink_plans ON public.workouts;
CREATE TRIGGER workouts_unlink_plans
  BEFORE DELETE ON public.workouts
  FOR EACH ROW EXECUTE FUNCTION public.unlink_plans_for_deleted_workout();

CREATE INDEX IF NOT EXISTS training_plans_athlete_date_idx
  ON public.training_plans (athlete_id, planned_date);
