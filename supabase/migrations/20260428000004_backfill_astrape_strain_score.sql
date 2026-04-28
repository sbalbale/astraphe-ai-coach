-- Backfill Astrape strain score on all existing workouts.
-- Strain score is a simple 0–100 proxy derived from TSS (150 ~= very hard day).
UPDATE workouts
SET astrape_strain_score = LEAST(
  100,
  GREATEST(0, ROUND((COALESCE(tss, 0) / 150.0) * 100))
)
WHERE astrape_strain_score IS NULL;

