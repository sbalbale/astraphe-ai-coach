-- Security advisor fixes:
-- 1. Pin match_coach_memories search_path for all live overloads.
-- 2. Remove anonymous table SELECT grants that expose schema via pg_graphql.

DO $$
DECLARE
  memory_fn regprocedure;
  matched_count integer := 0;
BEGIN
  FOR memory_fn IN
    SELECT p.oid::regprocedure
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'match_coach_memories'
  LOOP
    EXECUTE format('ALTER FUNCTION %s SECURITY INVOKER', memory_fn);
    EXECUTE format('ALTER FUNCTION %s SET search_path = public, extensions', memory_fn);
    matched_count := matched_count + 1;
  END LOOP;

  IF matched_count = 0 THEN
    RAISE EXCEPTION 'public.match_coach_memories function was not found';
  END IF;
END $$;

DO $$
DECLARE
  table_name text;
  tables text[] := ARRAY[
    'activity_laps',
    'activity_streams',
    'athlete_analyses',
    'athletes',
    'biometrics',
    'coach_conversations',
    'coach_memories',
    'coach_messages',
    'oauth_tokens',
    'push_tokens',
    'sleep_periods',
    'training_plans',
    'tss_history',
    'workouts'
  ];
BEGIN
  FOREACH table_name IN ARRAY tables LOOP
    EXECUTE format('REVOKE SELECT ON TABLE public.%I FROM anon', table_name);
  END LOOP;
END $$;
