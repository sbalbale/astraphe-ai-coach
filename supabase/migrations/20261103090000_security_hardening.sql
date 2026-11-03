-- Security hardening from the 2026-11-02 audit.
--
-- Backward-compatible with the code that is still running while this migration
-- applies (CI runs migrations before the API rolls out): nothing the current backend
-- relies on is removed here. See notes on each section.

-- ---------------------------------------------------------------------------
-- 1. oauth_tokens: only the backend (service role) writes tokens. (Audit S-C2)
--    Users could INSERT/UPDATE their own rows, e.g. set external_user_id to someone
--    else's WHOOP/Strava id so that person's webhooks and token refreshes landed on
--    the attacker's row. Users keep SELECT of non-secret columns (sync status) and
--    nothing else; unlink runs through the backend.
-- ---------------------------------------------------------------------------
drop policy if exists "oauth_tokens_athlete_access" on public.oauth_tokens;
drop policy if exists "oauth_tokens_select_own" on public.oauth_tokens;

create policy "oauth_tokens_select_own" on public.oauth_tokens
  for select to authenticated
  using (athlete_id in (select a.id from public.athletes a where a.user_id = (select auth.uid())));

revoke insert, update, delete, truncate, references, trigger on public.oauth_tokens from authenticated, anon;
revoke select on public.oauth_tokens from authenticated, anon;
grant select (id, athlete_id, provider, external_user_id, expires_at, created_at, updated_at)
  on public.oauth_tokens to authenticated;

-- One local account per provider identity. Created only when existing data allows it;
-- otherwise warn so the duplicates can be cleaned up and this re-run.
do $$
begin
  if exists (
    select 1 from public.oauth_tokens
    where external_user_id is not null
    group by provider, external_user_id having count(*) > 1
  ) then
    raise warning 'oauth_tokens has duplicate (provider, external_user_id); unique index NOT created';
  else
    create unique index if not exists oauth_tokens_provider_external_user_uniq
      on public.oauth_tokens (provider, external_user_id)
      where external_user_id is not null;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 2. Third-party OAuth (MCP) tokens are read-only at the database. (Audit X-H1)
--    Supabase's OAuth server issues normal `authenticated` JWTs with a `client_id`
--    claim; the MCP server only reads. A restrictive policy blocks every write made
--    with such a token on every RLS-protected public table.
-- ---------------------------------------------------------------------------
do $$
declare
  t record;
begin
  for t in
    select c.relname
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
  loop
    execute format('drop policy if exists no_oauth_client_insert on public.%I', t.relname);
    execute format('drop policy if exists no_oauth_client_update on public.%I', t.relname);
    execute format('drop policy if exists no_oauth_client_delete on public.%I', t.relname);
    execute format(
      'create policy no_oauth_client_insert on public.%I as restrictive for insert to authenticated
         with check ((select auth.jwt() ->> ''client_id'') is null)', t.relname);
    execute format(
      'create policy no_oauth_client_update on public.%I as restrictive for update to authenticated
         using ((select auth.jwt() ->> ''client_id'') is null)
         with check ((select auth.jwt() ->> ''client_id'') is null)', t.relname);
    execute format(
      'create policy no_oauth_client_delete on public.%I as restrictive for delete to authenticated
         using ((select auth.jwt() ->> ''client_id'') is null)', t.relname);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 3. athletes: server-owned columns can't be changed with a user session.
--    (Audit X-M5, X-L9/X-L14 for tier) The profile PATCH never sends these; Strava
--    linking and admin tier changes use the service role. Without this a user could
--    claim someone else's strava_athlete_id (globally unique) and break their connect.
-- ---------------------------------------------------------------------------
create or replace function public.protect_athlete_server_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if coalesce(auth.role(), '') in ('authenticated', 'anon') then
    if new.tier is distinct from old.tier
       or new.strava_athlete_id is distinct from old.strava_athlete_id
       or new.user_id is distinct from old.user_id then
      raise exception 'tier, strava_athlete_id and user_id are managed by the server'
        using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists protect_athlete_server_columns on public.athletes;
create trigger protect_athlete_server_columns
  before update on public.athletes
  for each row execute function public.protect_athlete_server_columns();

-- ---------------------------------------------------------------------------
-- 4. workouts: provider ids unique per athlete, not globally. (Audit X-M5)
--    Strava activity ids are public; with a global constraint anyone could insert a
--    workout claiming a victim's activity id and that activity would never import
--    for its owner. No code names these constraints (ingest dedupes by lookup).
-- ---------------------------------------------------------------------------
alter table public.workouts drop constraint if exists workouts_strava_activity_id_key;
alter table public.workouts drop constraint if exists workouts_garmin_activity_id_key;
alter table public.workouts drop constraint if exists workouts_external_id_unique;
-- Idempotent so a re-run (or a reset after a manual apply) doesn't fail.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'workouts_athlete_strava_activity_uniq') then
    alter table public.workouts add constraint workouts_athlete_strava_activity_uniq unique (athlete_id, strava_activity_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'workouts_athlete_garmin_activity_uniq') then
    alter table public.workouts add constraint workouts_athlete_garmin_activity_uniq unique (athlete_id, garmin_activity_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'workouts_athlete_source_external_uniq') then
    alter table public.workouts add constraint workouts_athlete_source_external_uniq unique (athlete_id, source, external_id);
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 5. sleep_periods: key per athlete. (Audit D-C1)
--    Garmin nights are `garmin:YYYY-MM-DD`, identical for every Garmin user, and the
--    (source, external_id) key let one athlete's sync take over another's night.
--    The new code upserts on (athlete_id, source, external_id). The old constraint
--    stays for now because the code still running during this migration upserts on
--    it; while both exist, a cross-athlete collision fails instead of overwriting.
--    FOLLOW-UP (after this release is deployed):
--      alter table public.sleep_periods drop constraint sleep_periods_external_id_unique;
-- ---------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'sleep_periods_athlete_source_external_uniq') then
    alter table public.sleep_periods
      add constraint sleep_periods_athlete_source_external_uniq unique (athlete_id, source, external_id);
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Storage. (Audit X-M3, X-M4)
--    Only the backend (service role) writes activity-stream blobs; users could upload
--    a decompression bomb into their folder and point a workout at it. Cap sizes.
-- ---------------------------------------------------------------------------
drop policy if exists "activity_streams_storage_insert_own" on storage.objects;
drop policy if exists "activity_streams_storage_update_own" on storage.objects;
drop policy if exists "activity_streams_storage_delete_own" on storage.objects;

update storage.buckets set file_size_limit = 10485760 where id = 'activity-streams';  -- 10 MB
update storage.buckets set file_size_limit = 10485760 where id = 'coach-uploads';     -- 10 MB

-- ---------------------------------------------------------------------------
-- 7. Least privilege for API roles. (Audit X-L10)
--    `anon` held every privilege (incl. TRUNCATE) on every table and on future
--    tables. Harmless while RLS is on everywhere, dangerous the moment a migration
--    forgets it. Nothing in the app queries as anon.
-- ---------------------------------------------------------------------------
revoke all on all tables in schema public from anon;
revoke truncate, references, trigger on all tables in schema public from authenticated;
alter default privileges for role postgres in schema public revoke all on tables from anon;
alter default privileges for role postgres in schema public revoke truncate, references, trigger on tables from authenticated;
