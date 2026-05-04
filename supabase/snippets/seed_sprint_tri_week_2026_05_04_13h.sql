-- Seed a sprint-tri-focused 13h week into training_plans (additive; no deletes).
-- Week of 2026-05-04 (Mon) through 2026-05-10 (Sun)
-- Athlete: 31409b63-c411-43f1-b4f4-83ff9af79be8
--
-- Notes:
-- - This is intentionally higher volume than typical sprint prep (per user request 12–15h).
-- - Use primary_zone and structure columns (now present).

insert into public.training_plans (
  athlete_id,
  planned_date,
  sport,
  title,
  description,
  duration_min,
  target_tss,
  primary_zone,
  structure,
  status
)
values
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-04',
  'strength',
  'Guidelines / Progression + Recovery',
  'Progression: Increase total weekly volume by no more than 10% per week to avoid excessive ATL accumulation. Recovery hard-stop: If skin temperature deviates > 1.0°C from baseline, cease all training and transition to complete rest.',
  0,
  0,
  'Recovery',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-04',
  'swimming',
  'Swim Endurance + Drills (75m)',
  'Z2 aerobic swim + technique. Keep effort controlled.',
  75,
  45,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-05',
  'cycling',
  'Bike Threshold (120m)',
  'Main set: sustained threshold focus; cap intensity if TSB trends < -20.',
  120,
  95,
  'Threshold',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-06',
  'running',
  'Run Tempo (60m)',
  'Controlled tempo; do not turn into VO2max. Stop if HRV suppressed.',
  60,
  55,
  'Tempo',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-07',
  'swimming',
  'Swim Threshold (75m)',
  'Aerobic warm-up then threshold reps. Keep form strict.',
  75,
  60,
  'Threshold',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-08',
  'cycling',
  'Bike Endurance (120m)',
  'Strict Z2 endurance; nutrition practice.',
  120,
  70,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-09',
  'cycling',
  'Brick Bike Race-Prep (180m)',
  'Z2 bulk with race-pace blocks late; keep cadence controlled.',
  180,
  115,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-09',
  'running',
  'Brick Run Off-Bike (45m)',
  'Short run off-bike at upper Z2 / low tempo; keep it economical.',
  45,
  45,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-10',
  'cycling',
  'Bike Long Endurance (150m)',
  'Z2 endurance. If fatigue accumulates (TSB < -20), cut by 30%.',
  150,
  85,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-10',
  'running',
  'Run Endurance (90m)',
  'Z2 endurance; soft surface preferred.',
  90,
  60,
  'Endurance',
  '[]'::jsonb,
  'planned'
);

