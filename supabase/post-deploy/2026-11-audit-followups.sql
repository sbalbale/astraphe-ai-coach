-- Apply AFTER the fix/audit-2026-11 backend is live everywhere, then move this into
-- supabase/migrations/ with a new timestamp so other environments get it.
-- (CI runs migrations *before* deploying the API, so these can't ship with the code:
-- the old code still relies on what they remove.)

-- 1. sleep_periods: drop the cross-athlete key. (Audit D-C1)
--    The new code upserts on (athlete_id, source, external_id).
alter table public.sleep_periods drop constraint if exists sleep_periods_external_id_unique;

-- 2. coach_messages: user sessions may only write role = 'user'. (Audit X-L9)
--    The new code writes coach/system turns with the service role.
drop policy if exists coach_messages_user_role_only_insert on public.coach_messages;
drop policy if exists coach_messages_user_role_only_update on public.coach_messages;
create policy coach_messages_user_role_only_insert on public.coach_messages
  as restrictive for insert to authenticated
  with check (role = 'user');
create policy coach_messages_user_role_only_update on public.coach_messages
  as restrictive for update to authenticated
  using (role = 'user')
  with check (role = 'user');
