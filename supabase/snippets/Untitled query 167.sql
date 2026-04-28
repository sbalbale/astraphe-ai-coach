alter table public.workouts
drop constraint workouts_sport_check;

alter table public.workouts
add constraint workouts_sport_check
check (
  sport in ('run','bike','swim','rowing','other','strength')  -- <- include strength
);