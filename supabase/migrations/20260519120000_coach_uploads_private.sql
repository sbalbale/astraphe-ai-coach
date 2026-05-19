-- Make coach-uploads bucket private so RLS policies control object access.
-- Objects and their data are not affected; only the public flag changes.
UPDATE storage.buckets SET public = false WHERE id = 'coach-uploads';
