-- 1. Create oauth_tokens table for third-party integrations
CREATE TABLE IF NOT EXISTS oauth_tokens (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  provider        TEXT NOT NULL,
  external_user_id TEXT,
  access_token    TEXT NOT NULL,
  refresh_token   TEXT,
  expires_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT oauth_tokens_athlete_provider_unique UNIQUE (athlete_id, provider)
);

ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "oauth_tokens_athlete_access" ON oauth_tokens
  FOR ALL USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 2. Add settings columns to athletes table
ALTER TABLE athletes 
ADD COLUMN IF NOT EXISTS notification_settings JSONB DEFAULT '{"readiness": true, "coach": true, "workouts": false, "insights": true}',
ADD COLUMN IF NOT EXISTS privacy_settings JSONB DEFAULT '{"share_data": true, "marketing": false}';
