-- RLS policy performance cleanup:
-- 1. Drop redundant display-name SELECT policies restored from production.
-- 2. Recreate one canonical authenticated policy per athlete-owned table.
-- 3. Cache auth.uid() with SELECT in policy predicates.
-- 4. Drop duplicate indexes added after equivalent original indexes.

DROP POLICY IF EXISTS "Athletes can view own laps" ON public.activity_laps;
DROP POLICY IF EXISTS "laps_self_access" ON public.activity_laps;
CREATE POLICY "laps_self_access"
  ON public.activity_laps
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own streams" ON public.activity_streams;
DROP POLICY IF EXISTS "streams_self_access" ON public.activity_streams;
CREATE POLICY "streams_self_access"
  ON public.activity_streams
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own analyses" ON public.athlete_analyses;
DROP POLICY IF EXISTS "athlete_analyses_athlete_access" ON public.athlete_analyses;
CREATE POLICY "athlete_analyses_athlete_access"
  ON public.athlete_analyses
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own profile" ON public.athletes;
DROP POLICY IF EXISTS "athletes_self_access" ON public.athletes;
CREATE POLICY "athletes_self_access"
  ON public.athletes
  FOR ALL
  TO authenticated
  USING (user_id = (SELECT auth.uid()))
  WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS "Athletes can view own biometrics" ON public.biometrics;
DROP POLICY IF EXISTS "biometrics_athlete_access" ON public.biometrics;
CREATE POLICY "biometrics_athlete_access"
  ON public.biometrics
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own conversations" ON public.coach_conversations;
DROP POLICY IF EXISTS "coach_conversations_athlete_access" ON public.coach_conversations;
CREATE POLICY "coach_conversations_athlete_access"
  ON public.coach_conversations
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own memories" ON public.coach_memories;
DROP POLICY IF EXISTS "coach_memories_athlete_access" ON public.coach_memories;
CREATE POLICY "coach_memories_athlete_access"
  ON public.coach_memories
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own messages" ON public.coach_messages;
DROP POLICY IF EXISTS "coach_messages_athlete_access" ON public.coach_messages;
CREATE POLICY "coach_messages_athlete_access"
  ON public.coach_messages
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own oauth tokens" ON public.oauth_tokens;
DROP POLICY IF EXISTS "oauth_tokens_athlete_access" ON public.oauth_tokens;
CREATE POLICY "oauth_tokens_athlete_access"
  ON public.oauth_tokens
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own push tokens" ON public.push_tokens;
DROP POLICY IF EXISTS "Athletes manage own push tokens" ON public.push_tokens;
DROP POLICY IF EXISTS "push_tokens_athlete_access" ON public.push_tokens;
CREATE POLICY "push_tokens_athlete_access"
  ON public.push_tokens
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own sleep" ON public.sleep_periods;
DROP POLICY IF EXISTS "sleep_periods_athlete_access" ON public.sleep_periods;
CREATE POLICY "sleep_periods_athlete_access"
  ON public.sleep_periods
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own training plans" ON public.training_plans;
DROP POLICY IF EXISTS "training_plans_athlete_access" ON public.training_plans;
CREATE POLICY "training_plans_athlete_access"
  ON public.training_plans
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own TSS history" ON public.tss_history;
DROP POLICY IF EXISTS "tss_history_athlete_access" ON public.tss_history;
CREATE POLICY "tss_history_athlete_access"
  ON public.tss_history
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP POLICY IF EXISTS "Athletes can view own workouts" ON public.workouts;
DROP POLICY IF EXISTS "workouts_athlete_access" ON public.workouts;
CREATE POLICY "workouts_athlete_access"
  ON public.workouts
  FOR ALL
  TO authenticated
  USING (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    athlete_id IN (
      SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

DROP INDEX IF EXISTS public.idx_athlete_analyses_lookup;
DROP INDEX IF EXISTS public.idx_biometrics_athlete_date;
DROP INDEX IF EXISTS public.idx_tss_history_athlete_date;
DROP INDEX IF EXISTS public.idx_workouts_athlete_started;

-- SECURITY DEFINER functions should not be callable through public API roles.
-- handle_new_user() is a trigger function; rls_auto_enable() may be used by an
-- event trigger in some environments. Revoking API execution preserves internal
-- trigger behavior while removing REST/RPC exposure.
REVOKE ALL ON FUNCTION public.handle_new_user() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM anon, authenticated;
