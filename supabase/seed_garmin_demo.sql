-- Local-dev demo data: 12 weeks of Garmin-sourced training + biometrics for the
-- seeded athlete (52c00ba6-...). Run AFTER seed_athlete.sql:
--   docker exec -i supabase_db_astraphe-ai-coach psql -U postgres < supabase/seed_garmin_demo.sql
-- Idempotent: clears and regenerates this athlete's workouts/biometrics/tss_history.
-- Dev login: test@example.com / password123

DO $$
DECLARE
  aid UUID := '52c00ba6-d91b-4eb3-b0ad-c533161da9bd';
  d DATE;
  today DATE := CURRENT_DATE;
  dow INT;
  wk INT;
  tss NUMERIC;
  sport TEXT;
  title TEXT;
  dur INT;
  wid UUID;
  ctl NUMERIC := 48;
  atl NUMERIC := 48;
  r NUMERIC;
BEGIN
  -- Dev login so the app can sign in locally.
  UPDATE auth.users
  SET encrypted_password = crypt('password123', gen_salt('bf')),
      email_confirmed_at = COALESCE(email_confirmed_at, now()),
      -- GoTrue fails with "Database error querying schema" if these are NULL.
      confirmation_token = COALESCE(confirmation_token, ''), recovery_token = COALESCE(recovery_token, ''),
      email_change_token_new = COALESCE(email_change_token_new, ''), email_change = COALESCE(email_change, ''),
      email_change_token_current = COALESCE(email_change_token_current, ''),
      reauthentication_token = COALESCE(reauthentication_token, ''),
      phone_change = COALESCE(phone_change, ''), phone_change_token = COALESCE(phone_change_token, '')
  WHERE id = aid;

  INSERT INTO auth.identities (id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at)
  SELECT gen_random_uuid(), id, id::text, 'email',
         jsonb_build_object('sub', id::text, 'email', email, 'email_verified', true), now(), now(), now()
  FROM auth.users
  WHERE id = aid AND NOT EXISTS (SELECT 1 FROM auth.identities WHERE user_id = aid);

  UPDATE public.athletes
  SET ftp_watts = 262, max_hr = 188, resting_hr = 48, threshold_hr = 168,
      hrv_baseline = 56, rhr_baseline = 48, weekly_tss_target = 450,
      sport_focus = '{bike,run}', vo2max_est = 56
  WHERE id = aid;

  DELETE FROM public.tss_history WHERE athlete_id = aid;
  DELETE FROM public.biometrics WHERE athlete_id = aid;
  DELETE FROM public.workouts WHERE athlete_id = aid;

  FOR d IN SELECT generate_series(today - 83, today, '1 day')::date LOOP
    dow := EXTRACT(ISODOW FROM d)::int;          -- 1=Mon .. 7=Sun
    wk := ((today - d) / 7);                      -- 0 = this week
    r := (hashtext(d::text) % 100 + 100) % 100 / 100.0;  -- stable pseudo-random 0..1

    -- Weekly pattern: Mon/Thu key bike, Tue easy spin, Sat long ride, Sun run, Wed/Fri rest.
    tss := 0; sport := NULL;
    IF dow = 1 THEN sport := 'bike'; title := 'Sweet spot 3x12'; dur := 85; tss := 85 + r * 15;
    ELSIF dow = 2 THEN sport := 'bike'; title := 'Easy spin'; dur := 45; tss := 25 + r * 8;
    ELSIF dow = 4 THEN sport := 'bike'; title := 'VO2 5x4'; dur := 70; tss := 80 + r * 15;
    ELSIF dow = 6 THEN sport := 'bike'; title := 'Long endurance'; dur := 180; tss := 140 + r * 30;
    ELSIF dow = 7 THEN sport := 'run'; title := 'Easy run'; dur := 40; tss := 35 + r * 10;
    END IF;
    -- Recovery week every 4th week
    IF wk % 4 = 3 THEN tss := tss * 0.65; dur := (dur * 0.8)::int; END IF;
    -- Skip today's session: it is the planned workout, not yet done.
    IF d = today THEN sport := NULL; tss := 0; END IF;

    wid := NULL;
    IF sport IS NOT NULL THEN
      wid := gen_random_uuid();
      INSERT INTO public.workouts (
        id, athlete_id, source, primary_source, external_id, garmin_activity_id, sport, title,
        started_at, ended_at, duration_seconds, distance_m, elevation_gain_m,
        avg_hr, max_hr, avg_power_w, norm_power_w, avg_pace_sec_km, tss, if_value,
        strain_score, calories,
        hr_zone_1_pct, hr_zone_2_pct, hr_zone_3_pct, hr_zone_4_pct, hr_zone_5_pct
      ) VALUES (
        wid, aid, 'garmin', 'garmin', 'garmin-' || to_char(d, 'YYYYMMDD'),
        1000000000 + (d - DATE '2020-01-01'), sport, title,
        d + TIME '07:00', d + TIME '07:00' + make_interval(mins => dur), dur * 60,
        CASE WHEN sport = 'bike' THEN dur * 60 * 8.2 ELSE dur * 60 * 2.9 END,
        CASE WHEN sport = 'bike' THEN dur * 4 ELSE dur * 1.5 END,
        CASE WHEN sport = 'bike' THEN 138 + (r * 15)::int ELSE 148 + (r * 10)::int END,
        CASE WHEN sport = 'bike' THEN 171 ELSE 168 END,
        CASE WHEN sport = 'bike' THEN 190 + (r * 30)::int END,
        CASE WHEN sport = 'bike' THEN 205 + (r * 30)::int END,
        CASE WHEN sport = 'run' THEN 330 END,
        round(tss, 1),
        CASE WHEN sport = 'bike' THEN round((0.7 + tss / 600)::numeric, 3) ELSE 0.75 END,
        LEAST(21, (tss / 9)::int), (dur * 9)::int,
        10, 45, 25, 15, 5
      );
    END IF;

    -- PMC: 42d CTL / 7d ATL exponential averages.
    ctl := ctl + (tss - ctl) * (1 - exp(-1.0 / 42));
    atl := atl + (tss - atl) * (1 - exp(-1.0 / 7));
    INSERT INTO public.tss_history (athlete_id, date, daily_tss, workout_ids, ctl, atl, tsb)
    VALUES (aid, d, round(tss, 1), CASE WHEN wid IS NULL THEN NULL ELSE ARRAY[wid] END,
            round(ctl, 2), round(atl, 2), round(ctl - atl, 2));

    -- Biometrics: Garmin HRV / sleep / recovery, with some noise.
    INSERT INTO public.biometrics (
      athlete_id, date, hrv_rmssd, hrv_source, resting_hr,
      sleep_duration_min, sleep_score, sleep_deep_pct, sleep_rem_pct, sleep_light_pct, sleep_awake_pct,
      sleep_bedtime, sleep_wakeup, sleep_need_min, sleep_debt_min, sleep_in_bed_min,
      recovery_score, readiness_score, strain_score, day_strain, spo2_pct, skin_temp_deviation_c,
      metric_sources
    ) VALUES (
      aid, d, round((56 + (r - 0.5) * 16)::numeric, 1), 'garmin', 47 + (r * 5)::int,
      (420 + (r - 0.3) * 90)::int, (68 + r * 24)::int, 18, 22, 52, 8,
      d + TIME '23:00' - INTERVAL '1 day', d + TIME '06:45', 480, ((0.7 - r) * 60)::int + 30, 470,
      (55 + r * 35)::int, (60 + r * 30)::int, LEAST(21, (tss / 9)::int), round((tss / 9)::numeric, 1),
      96.5, round(((r - 0.5) * 0.6)::numeric, 2),
      '{"hrv_rmssd":"garmin","resting_hr":"garmin","sleep_duration_min":"garmin","sleep_score":"garmin"}'::jsonb
    );
  END LOOP;
END $$;

-- Marks Garmin as "connected" so the app shows data instead of the empty state.
-- Placeholder credentials: real syncs against Garmin will fail until you link for real.
INSERT INTO public.oauth_tokens (athlete_id, provider, external_user_id, access_token, refresh_token, expires_at)
VALUES ('52c00ba6-d91b-4eb3-b0ad-c533161da9bd', 'garmin', 'local-dev-garmin', 'local-dev-placeholder', 'local-dev-placeholder', now() + interval '10 years')
ON CONFLICT (athlete_id, provider) DO NOTHING;

-- Planned sessions for yesterday / today / tomorrow (Today screen's key session + day tabs).
DELETE FROM public.training_plans WHERE athlete_id = '52c00ba6-d91b-4eb3-b0ad-c533161da9bd';
INSERT INTO public.training_plans (athlete_id, planned_date, sport, title, description, duration_min, target_tss, primary_zone, status, generated_by, structure)
VALUES
('52c00ba6-d91b-4eb3-b0ad-c533161da9bd', CURRENT_DATE, 'bike', 'Sweet spot 3×12',
 'Three controlled blocks just under threshold. Keep cadence 88–95 and stay seated.', 85, 92, 'Tempo', 'planned', 'manual',
 '[{"name":"Warm-up","duration_minutes":20,"target_power_percent_ftp":60},
   {"name":"Sweet spot 1","duration_minutes":12,"target_power_percent_ftp":90},
   {"name":"Recovery","duration_minutes":5,"target_power_percent_ftp":50},
   {"name":"Sweet spot 2","duration_minutes":12,"target_power_percent_ftp":90},
   {"name":"Recovery","duration_minutes":5,"target_power_percent_ftp":50},
   {"name":"Sweet spot 3","duration_minutes":12,"target_power_percent_ftp":90},
   {"name":"Cool-down","duration_minutes":19,"target_power_percent_ftp":50}]'::jsonb),
('52c00ba6-d91b-4eb3-b0ad-c533161da9bd', CURRENT_DATE - 1, 'run', 'Easy run',
 'Conversational pace. Keep it boring.', 40, 35, 'Endurance', 'done', 'manual',
 '[{"name":"Easy","duration_minutes":40,"target_hr_zone":2}]'::jsonb),
('52c00ba6-d91b-4eb3-b0ad-c533161da9bd', CURRENT_DATE + 1, 'bike', 'Easy spin',
 'Flush the legs.', 45, 25, 'Recovery', 'planned', 'manual',
 '[{"name":"Steady","duration_minutes":45,"target_power_percent_ftp":55}]'::jsonb);
