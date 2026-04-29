-- Add gender to athlete profile anchors.
-- Used by HRSS/TRIMP models; keep as simple male/female for now.
ALTER TABLE athletes
ADD COLUMN IF NOT EXISTS gender TEXT NOT NULL DEFAULT 'male'
CHECK (lower(gender) IN ('male', 'female'));

