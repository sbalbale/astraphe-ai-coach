-- coach_memories: long-term semantic memory for the AI coach (per-athlete)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS coach_memories (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id  UUID        NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    embedding   VECTOR(768),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS coach_memories_athlete_idx
    ON coach_memories (athlete_id, created_at DESC);

CREATE INDEX IF NOT EXISTS coach_memories_embedding_idx
    ON coach_memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE coach_memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "coach_memories_athlete_access" ON coach_memories
    FOR ALL
    USING  (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()))
    WITH CHECK (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

CREATE OR REPLACE FUNCTION match_coach_memories(
    athlete_id      UUID,
    query_embedding VECTOR(768),
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
