-- All-day heart rate and workouts detected from it.
--
-- heart_rate_series: one row per athlete + local calendar day + source. Samples are
-- stored as two parallel arrays (seconds from start_at, bpm) rather than one row per
-- sample: Garmin's all-day series is a fixed 2-minute grid (720 samples a day), and a
-- day is always read whole. Offsets keep irregular sources (HealthKit) representable.
--
-- hr_detection_dismissals: windows the athlete deleted a detected workout from, so the
-- next sync doesn't detect it again.
--
-- workouts.source gains 'hr_detected' (lowest in the backend's SOURCE_PRIORITY).

CREATE TABLE IF NOT EXISTS public.heart_rate_series (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id    UUID NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  date          DATE NOT NULL,
  source        TEXT NOT NULL,
  start_at      TIMESTAMPTZ NOT NULL,
  offsets_sec   INTEGER[] NOT NULL,
  bpm           SMALLINT[] NOT NULL,
  resting_hr    SMALLINT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT heart_rate_series_unique UNIQUE (athlete_id, date, source),
  CONSTRAINT heart_rate_series_lengths CHECK (cardinality(offsets_sec) = cardinality(bpm))
);

ALTER TABLE public.heart_rate_series ENABLE ROW LEVEL SECURITY;

CREATE POLICY "heart_rate_series_athlete_access"
  ON public.heart_rate_series
  FOR ALL
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.heart_rate_series TO authenticated;
REVOKE SELECT ON TABLE public.heart_rate_series FROM anon;


CREATE TABLE IF NOT EXISTS public.hr_detection_dismissals (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id  UUID NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  started_at  TIMESTAMPTZ NOT NULL,
  ended_at    TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT hr_detection_dismissals_order CHECK (ended_at > started_at)
);

CREATE INDEX IF NOT EXISTS hr_detection_dismissals_athlete_started
  ON public.hr_detection_dismissals (athlete_id, started_at);

ALTER TABLE public.hr_detection_dismissals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "hr_detection_dismissals_athlete_access"
  ON public.hr_detection_dismissals
  FOR ALL
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.hr_detection_dismissals TO authenticated;
REVOKE SELECT ON TABLE public.hr_detection_dismissals FROM anon;


ALTER TABLE public.workouts DROP CONSTRAINT IF EXISTS workouts_source_check;
ALTER TABLE public.workouts ADD CONSTRAINT workouts_source_check
  CHECK (
    source IN ('garmin', 'whoop', 'healthkit', 'manual', 'strava', 'intervals_icu', 'hr_detected')
  );
