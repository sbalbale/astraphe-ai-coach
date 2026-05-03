-- Remove legacy per-athlete AI settings column.
-- Model selection is now: JWT app_metadata.gemini_model -> backend .env GEMINI_MODEL

ALTER TABLE public.athletes
DROP COLUMN IF EXISTS ai_settings;

