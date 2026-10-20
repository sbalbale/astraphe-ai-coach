-- Photon (iMessage) coach channel.
--
-- workouts.notified_at: set atomically by the first replica that texts the
-- athlete about a workout, so Strava/WHOOP/Garmin re-deliveries and multiple
-- backend replicas never send a second text for the same session.
ALTER TABLE workouts
  ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;

-- messaging_events: inbound dedupe. The bridge may re-deliver a message after a
-- reconnect; the primary key makes the second insert fail so it is dropped.
CREATE TABLE IF NOT EXISTS messaging_events (
  provider    TEXT        NOT NULL,
  message_id  TEXT        NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, message_id)
);

-- Service-role only (the webhook uses the admin client); no policies means no
-- access for anon/authenticated roles.
ALTER TABLE messaging_events ENABLE ROW LEVEL SECURITY;

-- Workouts that already exist predate the Photon channel. Mark them notified so the first
-- deploy (and Garmin's next re-sync of recent activity) doesn't text about history.
-- Workouts from 2026-10-20 (athlete-local, EDT) onward are deliberately left eligible so the
-- first real texts come from them; the app's 12 hour window still applies on top of that.
-- Idempotent: only touches rows that are still un-notified.
UPDATE workouts
   SET notified_at = now()
 WHERE notified_at IS NULL
   AND started_at < TIMESTAMPTZ '2026-10-20 00:00:00-04';
