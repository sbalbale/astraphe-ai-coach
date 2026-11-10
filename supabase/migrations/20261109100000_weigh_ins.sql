-- Individual weigh-ins (the Weight screen) and a goal weight.
--
-- biometrics.weight_kg stays the one-per-day value the rest of the app reads. It is
-- recomputed from weigh-ins when the athlete logs or deletes one (backend
-- services/weight.py), and every other writer of biometrics.weight_kg (profile edit,
-- WHOOP, POST /biometrics/daily) gets a matching weigh-in from the trigger below.
-- Those have no real time of day: time_known = false, measured_at = local noon.
--
-- Deletes are soft (deleted_at) so the app can undo, and a re-sync of the same
-- reading (same source + external_id) never brings a deleted one back.

CREATE TABLE IF NOT EXISTS public.weigh_ins (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id    UUID NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  date          DATE NOT NULL,
  measured_at   TIMESTAMPTZ NOT NULL,
  weight_kg     NUMERIC(5,2) NOT NULL CHECK (weight_kg BETWEEN 20 AND 350),
  body_fat_pct  NUMERIC(4,1) CHECK (body_fat_pct IS NULL OR body_fat_pct BETWEEN 2 AND 75),
  source        TEXT NOT NULL,
  external_id   TEXT NOT NULL,
  time_known    BOOLEAN NOT NULL DEFAULT TRUE,
  deleted_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT weigh_ins_unique UNIQUE (athlete_id, source, external_id)
);

CREATE INDEX IF NOT EXISTS weigh_ins_athlete_measured
  ON public.weigh_ins (athlete_id, measured_at DESC);

ALTER TABLE public.weigh_ins ENABLE ROW LEVEL SECURITY;

CREATE POLICY "weigh_ins_athlete_access"
  ON public.weigh_ins
  FOR ALL
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.weigh_ins TO authenticated;
REVOKE SELECT ON TABLE public.weigh_ins FROM anon;


ALTER TABLE public.athletes
  ADD COLUMN IF NOT EXISTS goal_weight_kg NUMERIC(5,2)
  CHECK (goal_weight_kg IS NULL OR goal_weight_kg BETWEEN 20 AND 350);


-- A daily weight written without a weigh-in becomes one. Skipped when the day already
-- has a weigh-in from that source (including a deleted one: the athlete removed it),
-- and for a device repeating its previous value (WHOOP re-sends the profile weight
-- every day; that isn't a new weigh-in).
CREATE OR REPLACE FUNCTION public.biometrics_weight_to_weigh_in()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  src  TEXT;
  prev NUMERIC;
  off  INTEGER;
BEGIN
  IF NEW.weight_kg IS NULL OR NEW.weight_kg NOT BETWEEN 20 AND 350 THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.weight_kg IS NOT DISTINCT FROM NEW.weight_kg THEN
    RETURN NEW;
  END IF;
  src := COALESCE(NEW.metric_sources->>'weight_kg', 'manual');
  IF EXISTS (
    SELECT 1 FROM public.weigh_ins w
    WHERE w.athlete_id = NEW.athlete_id AND w.date = NEW.date AND w.source = src
  ) THEN
    RETURN NEW;
  END IF;
  SELECT w.weight_kg INTO prev
  FROM public.weigh_ins w
  WHERE w.athlete_id = NEW.athlete_id AND w.source = src AND w.date < NEW.date AND w.deleted_at IS NULL
  ORDER BY w.measured_at DESC
  LIMIT 1;
  IF src <> 'manual' AND prev IS NOT NULL AND abs(prev - NEW.weight_kg) < 0.05 THEN
    RETURN NEW;
  END IF;
  SELECT timezone_offset_min INTO off FROM public.athletes WHERE id = NEW.athlete_id;
  INSERT INTO public.weigh_ins (athlete_id, date, measured_at, weight_kg, source, external_id, time_known)
  VALUES (
    NEW.athlete_id,
    NEW.date,
    ((NEW.date + TIME '12:00') AT TIME ZONE 'UTC') - make_interval(mins => COALESCE(off, 0)),
    NEW.weight_kg,
    src,
    'daily:' || NEW.date,
    FALSE
  )
  ON CONFLICT (athlete_id, source, external_id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS biometrics_weight_to_weigh_in ON public.biometrics;
CREATE TRIGGER biometrics_weight_to_weigh_in
  AFTER INSERT OR UPDATE OF weight_kg ON public.biometrics
  FOR EACH ROW EXECUTE FUNCTION public.biometrics_weight_to_weigh_in();


-- Backfill: existing daily weights, with a source's unchanged repeats collapsed.
INSERT INTO public.weigh_ins (athlete_id, date, measured_at, weight_kg, source, external_id, time_known)
SELECT
  x.athlete_id,
  x.date,
  ((x.date + TIME '12:00') AT TIME ZONE 'UTC') - make_interval(mins => COALESCE(a.timezone_offset_min, 0)),
  x.weight_kg,
  x.src,
  'daily:' || x.date,
  FALSE
FROM (
  SELECT
    b.athlete_id,
    b.date,
    b.weight_kg,
    COALESCE(b.metric_sources->>'weight_kg', 'manual') AS src,
    lag(b.weight_kg) OVER (
      PARTITION BY b.athlete_id, COALESCE(b.metric_sources->>'weight_kg', 'manual')
      ORDER BY b.date
    ) AS prev
  FROM public.biometrics b
  WHERE b.weight_kg BETWEEN 20 AND 350
) x
JOIN public.athletes a ON a.id = x.athlete_id
WHERE x.prev IS NULL OR abs(x.prev - x.weight_kg) >= 0.05 OR x.src = 'manual'
ON CONFLICT (athlete_id, source, external_id) DO NOTHING;
