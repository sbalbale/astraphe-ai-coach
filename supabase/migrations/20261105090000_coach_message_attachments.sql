-- Documents (PDF, Word, Excel, CSV) attached to a coach chat message.
-- Each element: {"name": "...", "kind": "pdf|docx|xlsx|xls|csv|file", "content": "<extracted text>"}.
-- Kept with the message so the coach can still read an uploaded plan on later turns, and
-- the chat can show the attachment after a reload. Additive and defaulted, so the API
-- running before this deploy keeps working.

ALTER TABLE public.coach_messages
  ADD COLUMN IF NOT EXISTS attachments jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.coach_messages
  DROP CONSTRAINT IF EXISTS coach_messages_attachments_is_array;
ALTER TABLE public.coach_messages
  ADD CONSTRAINT coach_messages_attachments_is_array
  CHECK (jsonb_typeof(attachments) = 'array' AND jsonb_array_length(attachments) <= 3);
