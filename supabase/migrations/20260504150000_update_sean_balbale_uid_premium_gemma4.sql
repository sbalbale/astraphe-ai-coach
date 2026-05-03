-- Sean Balbale: JWT tier + Gemini/Gemma model override (updates only — no deletes).
UPDATE auth.users
SET raw_app_meta_data = COALESCE(raw_app_meta_data, '{}'::jsonb)
  || jsonb_build_object(
    'tier', 'premium',
    'gemini_model', 'gemma-4-26b-a4b-it'
  )
WHERE id = '4b9b328c-bc5a-464c-a88a-2c831d216b7b';

UPDATE public.athletes
SET tier = 'premium'
WHERE user_id = '4b9b328c-bc5a-464c-a88a-2c831d216b7b';
