-- Fix RLS initplan: wrap auth.uid() in (SELECT ...) for all policies
ALTER POLICY "athletes_self_access" ON public.athletes
  USING (user_id = (SELECT auth.uid()));

ALTER POLICY "workouts_athlete_access" ON public.workouts
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "biometrics_athlete_access" ON public.biometrics
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "tss_history_athlete_access" ON public.tss_history
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "training_plans_athlete_access" ON public.training_plans
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "oauth_tokens_athlete_access" ON public.oauth_tokens
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "sleep_periods_athlete_access" ON public.sleep_periods
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "coach_conversations_athlete_access" ON public.coach_conversations
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "coach_messages_athlete_access" ON public.coach_messages
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "athlete_analyses_athlete_access" ON public.athlete_analyses
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "streams_self_access" ON public.activity_streams
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "laps_self_access" ON public.activity_laps
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "push_tokens_athlete_access" ON public.push_tokens
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

ALTER POLICY "coach_memories_athlete_access" ON public.coach_memories
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = (SELECT auth.uid())));

-- Drop duplicate indexes (keep the named ones, drop the idx_ duplicates)
DROP INDEX IF EXISTS public.idx_workouts_athlete_started;
DROP INDEX IF EXISTS public.idx_biometrics_athlete_date;
DROP INDEX IF EXISTS public.idx_tss_history_athlete_date;
DROP INDEX IF EXISTS public.idx_athlete_analyses_lookup;

-- Revoke GraphQL anon/authenticated exposure
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
  LOOP
    EXECUTE format('REVOKE SELECT ON public.%I FROM anon, authenticated', t);
  END LOOP;
END;
$$;