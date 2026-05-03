-- Per-athlete AI model settings (Gemini-only for now)

ALTER TABLE public.athletes
ADD COLUMN IF NOT EXISTS ai_settings JSONB NOT NULL DEFAULT jsonb_build_object(
  'gemini_model', 'gemini-flash-lite-latest'
);

