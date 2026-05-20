-- Update match_coach_memories default threshold from 0.75 to 0.50
-- (gemini-embedding-001 produces lower cosine similarities than older 768-dim models)
CREATE OR REPLACE FUNCTION match_coach_memories(
    athlete_id      UUID,
    query_embedding VECTOR(3072),
    match_threshold FLOAT DEFAULT 0.50,
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
