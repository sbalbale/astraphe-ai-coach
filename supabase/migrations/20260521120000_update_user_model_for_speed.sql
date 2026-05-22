-- Update Sean Balbale to use gemma-4-26b-a4b-it for maximum reasoning depth and high usage limits.
UPDATE auth.users
SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
  || jsonb_build_object(
    'gemini_model', 'gemma-4-26b-a4b-it'
  )
WHERE id = '4b9b328c-bc5a-464c-a88a-2c831d216b7b';
