-- Coach-started notification threads and the notification log.
-- Additive (new columns have defaults), so the API running before this deploy keeps working.

-- ---------------------------------------------------------------------------------------
-- 1) Coach-started threads (post-workout debrief, missed session, weekly summary, …)
-- ---------------------------------------------------------------------------------------
ALTER TABLE public.coach_conversations
  ADD COLUMN IF NOT EXISTS started_by text NOT NULL DEFAULT 'athlete',
  -- What started a coach thread: 'debrief', 'missed', 'weekly', 'readiness', 'plan_changed'.
  ADD COLUMN IF NOT EXISTS trigger text,
  -- Context card for the thread, e.g. {"kind":"workout","id":"…","title":"…","meta":"…"}.
  ADD COLUMN IF NOT EXISTS context jsonb,
  ADD COLUMN IF NOT EXISTS unread boolean NOT NULL DEFAULT false;

ALTER TABLE public.coach_conversations DROP CONSTRAINT IF EXISTS coach_conversations_started_by_check;
ALTER TABLE public.coach_conversations
  ADD CONSTRAINT coach_conversations_started_by_check CHECK (started_by IN ('athlete', 'coach'));

-- Suggested one-tap replies under a coach message ("Felt good", "Legs were heavy").
ALTER TABLE public.coach_messages
  ADD COLUMN IF NOT EXISTS quick_replies text[] NOT NULL DEFAULT '{}';

-- ---------------------------------------------------------------------------------------
-- 2) Notification log: each notification is sent once, even with several API replicas.
-- ---------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notification_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id uuid NOT NULL REFERENCES public.athletes(id) ON DELETE CASCADE,
  kind text NOT NULL,
  -- e.g. the workout id for a debrief, '2026-11-08' for a daily one, '2026-W45' for weekly.
  dedupe_key text NOT NULL,
  conversation_id uuid REFERENCES public.coach_conversations(id) ON DELETE SET NULL,
  pushed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (athlete_id, kind, dedupe_key)
);

ALTER TABLE public.notification_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS notification_log_select_own ON public.notification_log;
CREATE POLICY notification_log_select_own ON public.notification_log
  FOR SELECT TO authenticated
  USING (athlete_id IN (SELECT id FROM public.athletes WHERE user_id = (SELECT auth.uid())));
-- Writes come from the API's service role only (no insert/update/delete policies).
