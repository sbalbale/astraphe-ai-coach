import { describe, expect, it } from 'vitest';
import { effectiveNotificationPrefs, enabledNotificationCount } from './notificationSettings';

describe('notification settings', () => {
  it('treats unsaved types as on, like the backend', () => {
    expect(enabledNotificationCount(null)).toBe(5);
    expect(enabledNotificationCount({})).toBe(5);
  });

  it('reads the old flat flags as a fallback', () => {
    const p = effectiveNotificationPrefs({ coach: false, readiness: false });
    expect(p.types.debrief.on).toBe(false);
    expect(p.types.plan.on).toBe(false);
    expect(p.types.ready.on).toBe(false);
    expect(enabledNotificationCount({ coach: false, readiness: false })).toBe(2);
  });

  it('keeps valid saved values and ignores bad ones', () => {
    const p = effectiveNotificationPrefs({
      types: { ready: { opt: '06:30', push: false }, weekly: { opt: 'Fri' } },
      quiet: { on: false, from: '23:00', to: '99:00' },
      texts: 'off'
    });
    expect(p.types.ready).toEqual({ on: true, opt: '06:30', push: false });
    expect(p.types.weekly.opt).toBe('Sun');
    expect(p.quiet).toEqual({ on: false, from: '23:00', to: '07:00' });
    expect(p.texts).toBe('off');
  });
});
