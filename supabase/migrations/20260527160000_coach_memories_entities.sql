-- Structured coach_memories entities for upserts/edits (race goals, etc.)
-- Keeps backward compatibility: existing rows remain valid with NULL metadata.

ALTER TABLE coach_memories
  ADD COLUMN IF NOT EXISTS memory_type TEXT,
  ADD COLUMN IF NOT EXISTS entity_key TEXT,
  ADD COLUMN IF NOT EXISTS event_date DATE,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Optional: keep memory_type constrained to a small known set (expand later).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'coach_memories_memory_type_check'
  ) THEN
    ALTER TABLE coach_memories
      ADD CONSTRAINT coach_memories_memory_type_check
      CHECK (memory_type IS NULL OR memory_type IN ('note','race'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS coach_memories_entity_idx
  ON coach_memories (athlete_id, memory_type, entity_key, updated_at DESC);

-- Backfill legacy rows to 'note' so new code can reason uniformly.
UPDATE coach_memories
SET memory_type = 'note'
WHERE memory_type IS NULL;

