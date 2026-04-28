-- Add time_format column to athletes table
ALTER TABLE athletes
  ADD COLUMN IF NOT EXISTS time_format TEXT NOT NULL DEFAULT '12h';
