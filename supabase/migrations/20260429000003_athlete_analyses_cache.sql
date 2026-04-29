-- Cached narrative analyses (Gemini-generated) keyed by input fingerprint.
-- Used to avoid repeated LLM calls unless underlying data changes.

CREATE TABLE IF NOT EXISTS athlete_analyses (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id    UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  analysis_type TEXT NOT NULL CHECK (analysis_type IN ('recovery','sleep','strain','training_load')),
  scope_key     TEXT NOT NULL, -- e.g. YYYY-MM-DD for daily pages; other scopes allowed
  fingerprint   TEXT NOT NULL, -- sha256 of canonical context JSON
  model         TEXT,
  content       TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT athlete_analyses_unique_scope UNIQUE (athlete_id, analysis_type, scope_key)
);

CREATE INDEX IF NOT EXISTS athlete_analyses_athlete_type_scope
  ON athlete_analyses (athlete_id, analysis_type, scope_key);

CREATE INDEX IF NOT EXISTS athlete_analyses_athlete_updated
  ON athlete_analyses (athlete_id, updated_at DESC);

ALTER TABLE athlete_analyses ENABLE ROW LEVEL SECURITY;

-- Mirror other athlete-owned table policies: allow access only for the athlete row(s)
-- owned by the authenticated user.
CREATE POLICY "athlete_analyses_athlete_access" ON athlete_analyses
  FOR ALL
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()))
  WITH CHECK (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

