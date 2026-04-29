-- Coach chat history + uploads
-- Creates:
-- - coach_conversations
-- - coach_messages
-- - storage bucket: coach-uploads

-- 1) Conversations
CREATE TABLE IF NOT EXISTS coach_conversations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id  UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  title       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS coach_conversations_athlete_updated
  ON coach_conversations (athlete_id, updated_at DESC);

ALTER TABLE coach_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_conversations_athlete_access" ON coach_conversations
  FOR ALL
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()))
  WITH CHECK (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 2) Messages
CREATE TABLE IF NOT EXISTS coach_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES coach_conversations(id) ON DELETE CASCADE,
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','ai','system')),
  content         TEXT,
  image_urls      TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS coach_messages_conversation_created
  ON coach_messages (conversation_id, created_at ASC);
CREATE INDEX IF NOT EXISTS coach_messages_athlete_created
  ON coach_messages (athlete_id, created_at DESC);

ALTER TABLE coach_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_messages_athlete_access" ON coach_messages
  FOR ALL
  USING (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()))
  WITH CHECK (athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid()));

-- 3) Storage bucket for chat uploads
INSERT INTO storage.buckets (id, name, public)
VALUES ('coach-uploads', 'coach-uploads', true)
ON CONFLICT (id) DO NOTHING;

-- Storage RLS: objects are stored under prefix: coach/<auth.uid()>/<conversation_id>/<filename>
-- Allow read for own objects
CREATE POLICY "coach_uploads_read_own" ON storage.objects
  FOR SELECT
  USING (
    bucket_id = 'coach-uploads'
    AND split_part(name, '/', 2) = auth.uid()::text
  );

-- Allow upload for own objects
CREATE POLICY "coach_uploads_insert_own" ON storage.objects
  FOR INSERT
  WITH CHECK (
    bucket_id = 'coach-uploads'
    AND split_part(name, '/', 2) = auth.uid()::text
  );

-- Allow delete for own objects
CREATE POLICY "coach_uploads_delete_own" ON storage.objects
  FOR DELETE
  USING (
    bucket_id = 'coach-uploads'
    AND split_part(name, '/', 2) = auth.uid()::text
  );

