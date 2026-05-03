-- Per-user AI model (JWT app_metadata.gemini_model) for Sean Balbale test user
UPDATE auth.users
SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
  || jsonb_build_object('gemini_model', 'gemma-4-26b-a4b-it')
WHERE id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd';
