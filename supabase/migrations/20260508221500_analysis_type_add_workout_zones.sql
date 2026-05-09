ALTER TABLE athlete_analyses DROP CONSTRAINT IF EXISTS athlete_analyses_analysis_type_check;

ALTER TABLE athlete_analyses ADD CONSTRAINT athlete_analyses_analysis_type_check
  CHECK (analysis_type IN (
    'recovery',
    'sleep',
    'strain',
    'training_load',
    'dashboard_summary',
    'workout',
    'time_in_zones'
  ));

