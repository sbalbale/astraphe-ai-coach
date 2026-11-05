-- Dated history of the anchors workout TSS is scored with (FTP, threshold pace and the units
-- that pace is written in). Each workout uses the values in effect on its date, so changing
-- FTP no longer re-scores every past ride against the new number.
--
-- Seeded with one row per athlete holding their current saved values from the start of time
-- (no earlier history exists to reconstruct). Later profile changes add a row from that day.

CREATE TABLE IF NOT EXISTS public.athlete_anchor_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id uuid NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  effective_from date NOT NULL,
  ftp_watts smallint,
  threshold_pace text,
  measurement_units text,
  source text NOT NULL DEFAULT 'manual'
    CHECK (source IN ('initial', 'manual', 'garmin', 'estimated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (athlete_id, effective_from)
);

CREATE INDEX IF NOT EXISTS athlete_anchor_history_athlete_idx
  ON public.athlete_anchor_history (athlete_id, effective_from DESC);

ALTER TABLE public.athlete_anchor_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS athlete_anchor_history_select_own ON public.athlete_anchor_history;
CREATE POLICY athlete_anchor_history_select_own ON public.athlete_anchor_history
  FOR SELECT TO authenticated
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));
-- Writes come from the API's service role only (no insert/update/delete policies).

INSERT INTO public.athlete_anchor_history (athlete_id, effective_from, ftp_watts, threshold_pace, measurement_units, source)
SELECT id, DATE '1900-01-01', ftp_watts, threshold_pace, measurement_units, 'initial'
FROM public.athletes
WHERE ftp_watts IS NOT NULL OR threshold_pace IS NOT NULL
ON CONFLICT (athlete_id, effective_from) DO NOTHING;
