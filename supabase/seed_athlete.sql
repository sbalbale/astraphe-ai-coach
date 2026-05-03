-- Seed a test user and athlete for local development
-- This allows the app to function even when not logged in (via TEST_ATHLETE_ID fallback)

DO $$
DECLARE
  test_user_id UUID := '52c00ba6-d91b-4eb3-b0ad-c533161da9bd'; -- Using the same ID for simplicity
BEGIN
  -- 1. Create a user in auth.users if it doesn't exist
  -- Note: We must use the auth schema which is managed by Supabase
  IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id = test_user_id) THEN
    INSERT INTO auth.users (id, instance_id, email, aud, role, raw_user_meta_data, raw_app_meta_data, is_super_admin, created_at, updated_at, last_sign_in_at, email_confirmed_at)
    VALUES (
      test_user_id,
      '00000000-0000-0000-0000-000000000000',
      'test@example.com',
      'authenticated',
      'authenticated',
      '{"full_name": "Sean Balbale"}',
      jsonb_build_object('gemini_model', 'gemma-4-26b-a4b-it'),
      false,
      now(),
      now(),
      now(),
      now()
    );
  END IF;

  -- 2. Create the athlete in public.athletes
  -- The trigger 'on_auth_user_created' might have already created it, but we'll ensure it has the correct ID
  IF NOT EXISTS (SELECT 1 FROM public.athletes WHERE id = test_user_id) THEN
    INSERT INTO public.athletes (id, user_id, display_name, weight_kg, height_cm, max_hr, hrv_baseline, rhr_baseline)
    VALUES (
      test_user_id,
      test_user_id,
      'Sean Balbale',
      75.0,
      180.0,
      190,
      65.0,
      50.0
    )
    ON CONFLICT (user_id) DO UPDATE SET id = test_user_id;
  END IF;

END $$;

-- Keep hosted model aligned for seeded Sean even if auth.users predates raw_app_meta_data on insert.
UPDATE auth.users
SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
  || jsonb_build_object('gemini_model', 'gemma-4-26b-a4b-it')
WHERE id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd';
