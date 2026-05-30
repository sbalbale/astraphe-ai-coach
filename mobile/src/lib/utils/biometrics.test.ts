import { describe, expect, it } from 'vitest';
import { currentRecoveryState, firstPositiveFiniteNumber } from './biometrics';

describe('firstPositiveFiniteNumber', () => {
  it('returns first finite positive number', () => {
    expect(firstPositiveFiniteNumber(0, null, '63', 70)).toBe(63);
    expect(firstPositiveFiniteNumber(undefined, 49)).toBe(49);
  });

  it('returns null when no valid candidates', () => {
    expect(firstPositiveFiniteNumber(0, -1, '', null)).toBeNull();
  });
});

describe('currentRecoveryState', () => {
  const now = new Date('2026-05-30T02:00:00');

  it('prefers today row when recovery_score is finite', () => {
    const state = currentRecoveryState(
      [
        { date: '2026-05-29', recovery_score: 50 },
        { date: '2026-05-30', recovery_score: 72, readiness_score: 70 }
      ],
      0,
      now
    );
    expect(state.hasTodayRow).toBe(true);
    expect(state.row?.recovery_score).toBe(72);
    expect(state.isStale).toBe(false);
    expect(state.ageHours).toBe(0);
  });

  it('carries forward when today has only TSB-only readiness', () => {
    const state = currentRecoveryState(
      [
        { date: '2026-05-29', recovery_score: 63, readiness_score: 59 },
        { date: '2026-05-30', readiness_score: 49 }
      ],
      0,
      now
    );
    expect(state.hasTodayRow).toBe(false);
    expect(state.row?.recovery_score).toBe(63);
    expect(state.date).toBe('2026-05-29');
  });

  it('returns empty when no recovery rows exist', () => {
    const state = currentRecoveryState([{ date: '2026-05-30', readiness_score: 49 }], 0, now);
    expect(state.row).toBeNull();
    expect(state.hasTodayRow).toBe(false);
  });

  it('marks stale when carried row is older than 36h', () => {
    const oldWake = new Date('2026-05-27T06:00:00').toISOString();
    const state = currentRecoveryState(
      [{ date: '2026-05-27', recovery_score: 80, sleep_wakeup: oldWake }],
      0,
      now
    );
    expect(state.isStale).toBe(true);
    expect(state.ageHours).toBeGreaterThan(36);
  });
});
