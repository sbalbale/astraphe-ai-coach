-- Phase 2: store activity stream time_series in Storage as gzip JSON; metadata in Postgres.

INSERT INTO storage.buckets (id, name, public)
VALUES ('activity-streams', 'activity-streams', false)
ON CONFLICT (id) DO UPDATE SET public = false;

ALTER TABLE public.activity_streams
  ADD COLUMN IF NOT EXISTS storage_path TEXT,
  ADD COLUMN IF NOT EXISTS byte_size BIGINT,
  ADD COLUMN IF NOT EXISTS content_encoding TEXT DEFAULT 'gzip';

-- Allow rows with storage_path only (time_series moved to object store).
ALTER TABLE public.activity_streams
  ALTER COLUMN time_series DROP NOT NULL;

-- Object key layout: {athlete_id}/{workout_id}.json.gz
CREATE POLICY "activity_streams_storage_select_own"
  ON storage.objects
  FOR SELECT
  USING (
    bucket_id = 'activity-streams'
    AND (storage.foldername(name))[1] = (
      SELECT id::text FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY "activity_streams_storage_insert_own"
  ON storage.objects
  FOR INSERT
  WITH CHECK (
    bucket_id = 'activity-streams'
    AND (storage.foldername(name))[1] = (
      SELECT id::text FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY "activity_streams_storage_update_own"
  ON storage.objects
  FOR UPDATE
  USING (
    bucket_id = 'activity-streams'
    AND (storage.foldername(name))[1] = (
      SELECT id::text FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    bucket_id = 'activity-streams'
    AND (storage.foldername(name))[1] = (
      SELECT id::text FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY "activity_streams_storage_delete_own"
  ON storage.objects
  FOR DELETE
  USING (
    bucket_id = 'activity-streams'
    AND (storage.foldername(name))[1] = (
      SELECT id::text FROM public.athletes WHERE user_id = (SELECT auth.uid())
    )
  );

NOTIFY pgrst, 'reload schema';
