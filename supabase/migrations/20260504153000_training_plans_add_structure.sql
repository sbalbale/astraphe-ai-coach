-- Extend training_plans to support strict planned-workout schema
-- (primary zone + structured intervals stored as JSONB).
--
-- Backwards compatible: existing columns remain in place for legacy /v1/plan consumers.

ALTER TABLE public.training_plans
  ADD COLUMN IF NOT EXISTS primary_zone TEXT,
  ADD COLUMN IF NOT EXISTS structure JSONB;

