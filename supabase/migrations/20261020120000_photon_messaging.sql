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
