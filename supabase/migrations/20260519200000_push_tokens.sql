CREATE TABLE IF NOT EXISTS push_tokens (
  id          uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  athlete_id  uuid        NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  token       text        NOT NULL,
  platform    text        NOT NULL CHECK (platform IN ('ios', 'android', 'web')),
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now(),
  UNIQUE (athlete_id, token)
);

CREATE INDEX IF NOT EXISTS push_tokens_athlete_idx ON push_tokens(athlete_id);

ALTER TABLE push_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Athletes manage own push tokens"
  ON push_tokens FOR ALL
  USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  )
  WITH CHECK (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
