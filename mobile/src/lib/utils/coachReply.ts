/** How long the chat waits for an async coach reply before giving up. */
export const COACH_REPLY_WAIT_MS = 180_000;

/**
 * Milliseconds still worth waiting for a reply to a user message sent at
 * `createdAt`, or 0 when that message is too old (or its time is unknown) for
 * a reply still to be coming. Reopening an old chat whose last turn is the
 * user's (e.g. the reply failed) must not lock the input for another 3 minutes.
 */
export function remainingReplyWaitMs(
  createdAt: string | null | undefined,
  now: number = Date.now(),
  windowMs: number = COACH_REPLY_WAIT_MS
): number {
  if (!createdAt) return 0;
  const sent = Date.parse(createdAt);
  if (!Number.isFinite(sent)) return 0;
  const age = now - sent;
  if (age < 0) return windowMs; // clock skew: the message is brand new
  return age >= windowMs ? 0 : windowMs - age;
}
