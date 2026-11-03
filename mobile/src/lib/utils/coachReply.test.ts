import { describe, expect, it } from 'vitest';
import { COACH_REPLY_WAIT_MS, remainingReplyWaitMs } from './coachReply';

describe('remainingReplyWaitMs', () => {
  const now = Date.parse('2026-11-03T12:00:00Z');

  it('waits the rest of the window for a recent message', () => {
    expect(remainingReplyWaitMs('2026-11-03T11:59:30Z', now)).toBe(COACH_REPLY_WAIT_MS - 30_000);
  });

  it('does not wait for an old message', () => {
    expect(remainingReplyWaitMs('2026-11-03T11:50:00Z', now)).toBe(0);
    expect(remainingReplyWaitMs('2026-11-03T11:57:00Z', now)).toBe(0);
  });

  it('does not wait when the time is missing or invalid', () => {
    expect(remainingReplyWaitMs(undefined, now)).toBe(0);
    expect(remainingReplyWaitMs('nonsense', now)).toBe(0);
  });

  it('treats a future timestamp (clock skew) as brand new', () => {
    expect(remainingReplyWaitMs('2026-11-03T12:00:05Z', now)).toBe(COACH_REPLY_WAIT_MS);
  });
});
