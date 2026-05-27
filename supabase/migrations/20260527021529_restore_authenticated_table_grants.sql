-- Restore Data API table privileges for logged-in users.
-- RLS still restricts rows; table-level privileges are required before policies can run.
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
    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO authenticated',
      table_name
    );
    EXECUTE format('REVOKE SELECT ON TABLE public.%I FROM anon', table_name);
  END LOOP;
END;
$$;
