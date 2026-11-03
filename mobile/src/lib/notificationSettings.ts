/**
 * Notification types and their defaults. Must match the backend
 * (app/services/push.py: a missing key means *on*), so the toggles and the Me
 * page show what will actually be sent.
 */
export const NOTIFICATION_DEFAULTS = {
  readiness: true,
  coach: true,
  workouts: true,
  insights: true
} as const;

export type NotificationKey = keyof typeof NOTIFICATION_DEFAULTS;

export function effectiveNotificationSettings(raw: unknown): Record<NotificationKey, boolean> {
  const saved = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const out = { ...NOTIFICATION_DEFAULTS } as Record<NotificationKey, boolean>;
  for (const key of Object.keys(NOTIFICATION_DEFAULTS) as NotificationKey[]) {
    if (typeof saved[key] === 'boolean') out[key] = saved[key] as boolean;
  }
  return out;
}

/** How many notification types are on (as the backend would decide). */
export function enabledNotificationCount(raw: unknown): number {
  return Object.values(effectiveNotificationSettings(raw)).filter(Boolean).length;
}
