-- Sleep-stage timeline (hypnogram) segments, one row per contiguous stage block.
-- `date` is the same wake-date key biometrics / sleep_periods use for the night.

CREATE TABLE IF NOT EXISTS public.sleep_stage_segments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id  UUID NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  date        DATE NOT NULL,
  source      TEXT NOT NULL,
  stage       TEXT NOT NULL CHECK (stage IN ('deep', 'light', 'rem', 'awake')),
  start_at    TIMESTAMPTZ NOT NULL,
  end_at      TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT sleep_stage_segments_unique UNIQUE (athlete_id, source, start_at),
  CONSTRAINT sleep_stage_segments_order CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS sleep_stage_segments_athlete_date
  ON public.sleep_stage_segments (athlete_id, date);

ALTER TABLE public.sleep_stage_segments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "sleep_stage_segments_athlete_access"
  ON public.sleep_stage_segments
  FOR ALL
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));

-- RLS still restricts rows; table-level privileges are required before the policy runs.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sleep_stage_segments TO authenticated;
REVOKE SELECT ON TABLE public.sleep_stage_segments FROM anon;
