import { describe, expect, it } from 'vitest';
import { effectiveTier, hasPremiumAccess, trialEndsAtMs } from './tier';

const NOW = Date.parse('2026-11-20T00:00:00Z');

describe('effectiveTier', () => {
  it('keeps an active trial', () => {
    expect(effectiveTier({ tier: 'trial', trial_ends_at: '2026-11-25T00:00:00Z' }, null, NOW)).toBe('trial');
  });
  it('drops an expired trial to free', () => {
    expect(effectiveTier({ tier: 'trial', trial_ends_at: '2026-11-19T00:00:00Z' }, null, NOW)).toBe('free');
  });
  it('falls back to signup + 14 days', () => {
    expect(effectiveTier({ tier: 'trial' }, '2026-11-01T00:00:00Z', NOW)).toBe('free');
    expect(effectiveTier({ tier: 'trial' }, '2026-11-10T00:00:00Z', NOW)).toBe('trial');
    expect(trialEndsAtMs({}, '2026-11-01T00:00:00Z')).toBe(Date.parse('2026-11-15T00:00:00Z'));
  });
  it('leaves premium and free alone; unknown is free', () => {
    expect(effectiveTier({ tier: 'premium', trial_ends_at: '2000-01-01T00:00:00Z' }, null, NOW)).toBe('premium');
    expect(effectiveTier({ tier: 'gold' }, null, NOW)).toBe('free');
  });
});

describe('hasPremiumAccess', () => {
  it('opens premium features to premium and an active trial', () => {
    expect(hasPremiumAccess('premium')).toBe(true);
    expect(hasPremiumAccess('trial')).toBe(true);
    expect(hasPremiumAccess('free')).toBe(false);
  });
});
