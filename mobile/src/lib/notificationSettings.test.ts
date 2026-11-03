import { describe, expect, it } from 'vitest';
import { effectiveNotificationSettings, enabledNotificationCount } from './notificationSettings';

describe('notification settings', () => {
  it('treats unsaved types as on, like the backend', () => {
    expect(enabledNotificationCount(null)).toBe(4);
    expect(enabledNotificationCount({})).toBe(4);
    expect(effectiveNotificationSettings({ workouts: false }).workouts).toBe(false);
    expect(enabledNotificationCount({ coach: false, workouts: false })).toBe(2);
  });
});
