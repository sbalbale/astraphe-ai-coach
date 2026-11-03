-- New accounts start on a 14-day trial instead of premium. (Audit X-M6)
--
-- The tier lives in auth.users.raw_app_meta_data (what the backend and app read);
-- public.athletes.tier mirrors it. The trial end is stored next to it as
-- app_metadata.trial_ends_at so an admin can extend one. When it passes, the backend
-- treats the account as free and writes tier = 'free' back to both places.
-- Existing accounts are not changed.
--
-- Backward-compatible: code that predates this just sees a 'trial' tier.

alter table public.athletes alter column tier set default 'trial';

create or replace function public.set_default_user_tier()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  tier_raw text;
begin
  tier_raw := lower(coalesce(new.raw_app_meta_data->>'tier', ''));

  if tier_raw not in ('free', 'trial', 'premium') then
    new.raw_app_meta_data := coalesce(new.raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('tier', 'trial');
    tier_raw := 'trial';
  end if;

  if tier_raw = 'trial' and (new.raw_app_meta_data->>'trial_ends_at') is null then
    new.raw_app_meta_data := new.raw_app_meta_data
      || jsonb_build_object(
           'trial_ends_at',
           to_char((now() + interval '14 days') at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
         );
  end if;

  return new;
end;
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  tier_raw text;
  account_tier text;
begin
  tier_raw := lower(coalesce(new.raw_app_meta_data->>'tier', 'trial'));
  account_tier := case
    when tier_raw in ('free', 'trial', 'premium') then tier_raw
    else 'trial'
  end;

  insert into public.athletes (user_id, display_name, tier)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    account_tier
  );

  return new;
end;
$$;

revoke all on function public.set_default_user_tier() from public;
revoke execute on function public.set_default_user_tier() from anon, authenticated;
revoke all on function public.handle_new_user() from public;
revoke execute on function public.handle_new_user() from anon, authenticated;
