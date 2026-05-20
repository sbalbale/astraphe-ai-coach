-- Fix: gemini-embedding-001 returns 3072-dim vectors, not 768.
-- HNSW max is 2000 dims so we use sequential scan (fine for small per-athlete tables).
ALTER TABLE coach_memories DROP COLUMN IF EXISTS embedding;
ALTER TABLE coach_memories ADD COLUMN embedding VECTOR(3072);

CREATE OR REPLACE FUNCTION match_coach_memories(
    athlete_id      UUID,
    query_embedding VECTOR(3072),
    match_threshold FLOAT DEFAULT 0.75,
    match_count     INT   DEFAULT 5
)
RETURNS TABLE (
    id         UUID,
    content    TEXT,
    similarity FLOAT,
    created_at TIMESTAMPTZ
)
LANGUAGE sql STABLE
AS $$
    SELECT
        m.id,
        m.content,
        1 - (m.embedding <=> query_embedding) AS similarity,
        m.created_at
    FROM coach_memories m
    WHERE m.athlete_id = match_coach_memories.athlete_id
      AND 1 - (m.embedding <=> query_embedding) > match_threshold
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
$$;
