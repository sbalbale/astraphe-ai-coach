DO $$ 
DECLARE 
    r RECORD;
    new_date DATE;
BEGIN 
    RAISE NOTICE 'Starting sleep_periods date re-alignment...';
    
    FOR r IN (
        SELECT s.*, a.timezone_offset_min 
        FROM sleep_periods s
        JOIN athletes a ON s.athlete_id = a.id
        WHERE s.ended_at IS NOT NULL
    ) LOOP
        -- Calculate the correct local wake date
        new_date := (r.ended_at + (COALESCE(r.timezone_offset_min, 0) || ' minutes')::interval)::date;
        
        IF new_date != r.date THEN
            RAISE NOTICE 'Shifting sleep_period for athlete %: % -> % (Ended: %)', r.athlete_id, r.date, new_date, r.ended_at;
            
            -- Move the record
            DELETE FROM sleep_periods WHERE id = r.id;
            
            INSERT INTO sleep_periods (
                athlete_id, date, started_at, ended_at, duration_min, 
                in_bed_min, score, deep_pct, rem_pct, light_pct, awake_pct, 
                is_nap, source, external_id
            )
            VALUES (
                r.athlete_id, new_date, r.started_at, r.ended_at, r.duration_min, 
                r.in_bed_min, r.score, r.deep_pct, r.rem_pct, r.light_pct, r.awake_pct, 
                r.is_nap, r.source, r.external_id
            );
        END IF;
    END LOOP;

    RAISE NOTICE 'Starting biometric date re-alignment...';
    
    FOR r IN (
        SELECT b.*, a.timezone_offset_min 
        FROM biometrics b
        JOIN athletes a ON b.athlete_id = a.id
        WHERE b.sleep_wakeup IS NOT NULL
    ) LOOP
        -- Calculate the correct local wake date
        new_date := (r.sleep_wakeup + (COALESCE(r.timezone_offset_min, 0) || ' minutes')::interval)::date;
        
        IF new_date != r.date THEN
            RAISE NOTICE 'Shifting record for athlete %: % -> %', r.athlete_id, r.date, new_date;
            
            -- Because date is part of the Primary Key, we must delete and re-insert.
            -- We use a temporary record deletion to avoid duplicate key errors during the transition.
            
            DELETE FROM biometrics WHERE athlete_id = r.athlete_id AND date = r.date;
            
            INSERT INTO biometrics (
                athlete_id, date, source, hrv_rmssd, resting_hr, 
                sleep_duration_min, sleep_in_bed_min, sleep_score, 
                sleep_deep_pct, sleep_rem_pct, sleep_light_pct, sleep_awake_pct, 
                sleep_bedtime, sleep_wakeup, sleep_need_min, sleep_debt_min, 
                strain_score, skin_temp_deviation, spo2_pct, recovery_score, 
                readiness_score, is_nap
            )
            VALUES (
                r.athlete_id, new_date, r.source, r.hrv_rmssd, r.resting_hr, 
                r.sleep_duration_min, r.sleep_in_bed_min, r.sleep_score, 
                r.sleep_deep_pct, r.sleep_rem_pct, r.sleep_light_pct, r.sleep_awake_pct, 
                r.sleep_bedtime, r.sleep_wakeup, r.sleep_need_min, r.sleep_debt_min, 
                r.strain_score, r.skin_temp_deviation, r.spo2_pct, r.recovery_score, 
                r.readiness_score, r.is_nap
            )
            ON CONFLICT (athlete_id, date) DO UPDATE SET
                hrv_rmssd = EXCLUDED.hrv_rmssd,
                resting_hr = EXCLUDED.resting_hr,
                sleep_duration_min = EXCLUDED.sleep_duration_min,
                sleep_in_bed_min = EXCLUDED.sleep_in_bed_min,
                sleep_score = EXCLUDED.sleep_score,
                recovery_score = EXCLUDED.recovery_score,
                readiness_score = EXCLUDED.readiness_score,
                strain_score = EXCLUDED.strain_score;
        END IF;
    END LOOP;
    
    RAISE NOTICE 'Biometric date re-alignment complete.';
END $$;
