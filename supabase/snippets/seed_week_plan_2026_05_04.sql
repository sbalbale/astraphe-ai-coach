-- Seed a 17h aerobic base week into training_plans (additive; no deletes).
-- Athlete: 31409b63-c411-43f1-b4f4-83ff9af79be8

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
  'Guidelines / Recovery Rules',
  'Progression: Increase total weekly volume by no more than 10% per week to avoid excessive ATL accumulation. Recovery hard-stop: If skin temperature deviates > 1.0°C from your baseline, cease all training and transition to complete rest.',
  0,
  0,
  'Recovery',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-05',
  'swimming',
  'Swim Z2 Endurance (75m)',
  'Aerobic base. Strict Z2.',
  75,
  61,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-05',
  'running',
  'Run Z2 Endurance (75m)',
  'Aerobic base. Strict Z2.',
  75,
  61,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-06',
  'cycling',
  'Bike Z2 Endurance (180m)',
  'Aerobic base. Strict Z2.',
  180,
  147,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-07',
  'swimming',
  'Swim Z2 Endurance (60m)',
  'Aerobic base. Strict Z2.',
  60,
  49,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-07',
  'running',
  'Run Z2 Endurance (60m)',
  'Aerobic base. Strict Z2.',
  60,
  49,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-08',
  'cycling',
  'Bike Z2 Endurance (120m)',
  'Aerobic base. Strict Z2.',
  120,
  98,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-09',
  'cycling',
  'Brick: Bike Z2 (150m)',
  'Aerobic base. Strict Z2. Brick.',
  150,
  123,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-09',
  'running',
  'Brick: Run Z2 (120m)',
  'Aerobic base. Strict Z2. Brick.',
  120,
  98,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-10',
  'running',
  'Run Z2 Endurance (90m)',
  'Aerobic base. Strict Z2.',
  90,
  74,
  'Endurance',
  '[]'::jsonb,
  'planned'
),
(
  '31409b63-c411-43f1-b4f4-83ff9af79be8',
  '2026-05-10',
  'swimming',
  'Swim Z2 Endurance (90m)',
  'Aerobic base. Strict Z2.',
  90,
  74,
  'Endurance',
  '[]'::jsonb,
  'planned'
);

