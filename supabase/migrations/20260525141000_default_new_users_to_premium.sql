-- Give newly created accounts premium access by default.
-- Backend feature gates currently read the tier from auth.users.raw_app_meta_data,
-- while public.athletes.tier is kept in sync for profile/admin workflows.

ALTER TABLE public.athletes
ALTER COLUMN tier SET DEFAULT 'premium';

CREATE OR REPLACE FUNCTION public.set_default_user_tier()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  tier_raw TEXT;
BEGIN
  tier_raw := lower(coalesce(NEW.raw_app_meta_data->>'tier', ''));

  IF tier_raw NOT IN ('free', 'trial', 'premium') THEN
    NEW.raw_app_meta_data := coalesce(NEW.raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('tier', 'premium');
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_default_user_tier_before_insert ON auth.users;
CREATE TRIGGER set_default_user_tier_before_insert
  BEFORE INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.set_default_user_tier();

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  tier_raw TEXT;
  account_tier TEXT;
BEGIN
  tier_raw := lower(coalesce(NEW.raw_app_meta_data->>'tier', 'premium'));
  account_tier := CASE
    WHEN tier_raw IN ('free', 'trial', 'premium') THEN tier_raw
    ELSE 'premium'
  END;

  INSERT INTO public.athletes (user_id, display_name, tier)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
    account_tier
  );

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.set_default_user_tier() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.set_default_user_tier() FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_new_user() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM anon, authenticated;
