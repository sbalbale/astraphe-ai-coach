-- Prevent concurrent astraphe-api replicas from racing to refresh the same
-- OAuth token. token_refresh_loop() runs in-process in every replica with no
-- coordination; with 2 replicas (since the 2026-07-03 k3s migration), both
-- can call a provider's refresh endpoint for the same refresh_token at
-- nearly the same instant. This is the root cause of the WHOOP sync outage
-- that started 2026-07-04: the concurrent refresh attempts appear to have
-- tripped WHOOP's refresh-token reuse detection, permanently revoking the
-- grant. Defaulting to epoch (rather than NULL) keeps the claim query a
-- plain `< now()` comparison with no OR/IS NULL branch needed.
ALTER TABLE oauth_tokens
ADD COLUMN IF NOT EXISTS refresh_lock_expires_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01T00:00:00Z';
