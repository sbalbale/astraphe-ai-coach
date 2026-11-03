-- Audit follow-ups, applied once the fix/audit-2026-11 API was live everywhere
-- (deployed 2026-11-03). Previously supabase/post-deploy/2026-11-audit-followups.sql.

-- 1. sleep_periods: drop the cross-athlete key. (Audit D-C1, review F1)
--    The API upserts on (athlete_id, source, external_id). While the old global
--    (source, external_id) key existed, a second Garmin athlete's night
--    (`garmin:YYYY-MM-DD`, the same for everyone) failed on insert.
alter table public.sleep_periods drop constraint if exists sleep_periods_external_id_unique;

-- 2. coach_messages: user sessions may only write role = 'user'. (Audit X-L9)
--    The API writes coach/system turns with the service role.
drop policy if exists coach_messages_user_role_only_insert on public.coach_messages;
drop policy if exists coach_messages_user_role_only_update on public.coach_messages;
create policy coach_messages_user_role_only_insert on public.coach_messages
  as restrictive for insert to authenticated
  with check (role = 'user');
create policy coach_messages_user_role_only_update on public.coach_messages
  as restrictive for update to authenticated
  using (role = 'user')
  with check (role = 'user');
