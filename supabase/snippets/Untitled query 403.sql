     CREATE INDEX IF NOT EXISTS idx_biometrics_athlete_date
       ON biometrics(athlete_id, date DESC);

     CREATE INDEX IF NOT EXISTS idx_workouts_athlete_started
       ON workouts(athlete_id, started_at DESC);

     CREATE INDEX IF NOT EXISTS idx_tss_history_athlete_date
       ON tss_history(athlete_id, date DESC);

     CREATE INDEX IF NOT EXISTS idx_athlete_analyses_lookup
       ON athlete_analyses(athlete_id, analysis_type, scope_key);