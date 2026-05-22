CREATE INDEX idx_athlete_analyses_lookup ON public.athlete_analyses USING btree (athlete_id, analysis_type, scope_key);

CREATE INDEX idx_biometrics_athlete_date ON public.biometrics USING btree (athlete_id, date DESC);

CREATE INDEX idx_tss_history_athlete_date ON public.tss_history USING btree (athlete_id, date DESC);

CREATE INDEX idx_workouts_athlete_started ON public.workouts USING btree (athlete_id, started_at DESC);
