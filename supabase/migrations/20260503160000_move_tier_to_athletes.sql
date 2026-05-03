-- Move account tier source-of-truth from Auth metadata to public.athletes
-- Rationale: user/app metadata can be stale (and user metadata is user-editable).

ALTER TABLE public.athletes
ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'free';

-- Constrain allowed values (normalize in backfill first, then enforce).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'athletes_tier_check'
  ) THEN
    ALTER TABLE public.athletes
    ADD CONSTRAINT athletes_tier_check
    CHECK (tier IN ('free', 'trial', 'premium'));
  END IF;
END $$;

-- Backfill tier from auth.users metadata for existing accounts (best-effort).
-- Prefer raw_app_meta_data (admin-controlled) over raw_user_meta_data.
UPDATE public.athletes a
SET tier = CASE
  WHEN lower(coalesce(au.raw_app_meta_data->>'tier', '')) IN ('free', 'trial', 'premium')
    THEN lower(au.raw_app_meta_data->>'tier')
  WHEN lower(coalesce(au.raw_user_meta_data->>'tier', '')) IN ('free', 'trial', 'premium')
    THEN lower(au.raw_user_meta_data->>'tier')
  ELSE 'free'
END
FROM auth.users au
WHERE au.id = a.user_id;

