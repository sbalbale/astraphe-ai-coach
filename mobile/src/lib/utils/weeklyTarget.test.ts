import { describe, expect, it } from 'vitest';
import { weeklyTssTarget } from './weeklyTarget';

describe('weeklyTssTarget', () => {
  it('derives maintenance plus a small progression from CTL, rounded to 5', () => {
    // 61.2 * 7 * 1.05 = 449.8 -> 450
    expect(weeklyTssTarget(61.2)).toBe(450);
    // 48 * 7 * 1.05 = 352.8 -> 355
    expect(weeklyTssTarget(48)).toBe(355);
  });

  it('prefers the calculated value over a stale stored target', () => {
    expect(weeklyTssTarget(61.2, 200)).toBe(450);
  });

  it('falls back to the stored target when there is not enough history', () => {
    expect(weeklyTssTarget(0, 400)).toBe(400);
    expect(weeklyTssTarget(2, 350)).toBe(350);
    expect(weeklyTssTarget(null, 275.4)).toBe(275);
  });

  it('returns null when neither source is usable', () => {
    expect(weeklyTssTarget(undefined, undefined)).toBeNull();
    expect(weeklyTssTarget(NaN, 0)).toBeNull();
  });
});
