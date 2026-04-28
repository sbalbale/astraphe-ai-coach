-- Add policies for test athlete access
CREATE POLICY "athletes_test_access" ON public.athletes FOR SELECT USING (id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
CREATE POLICY "biometrics_test_access" ON public.biometrics FOR ALL USING (athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
CREATE POLICY "workouts_test_access" ON public.workouts FOR ALL USING (athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
CREATE POLICY "tss_history_test_access" ON public.tss_history FOR ALL USING (athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
CREATE POLICY "sleep_periods_test_access" ON public.sleep_periods FOR ALL USING (athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
CREATE POLICY "training_plans_test_access" ON public.training_plans FOR ALL USING (athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd');
