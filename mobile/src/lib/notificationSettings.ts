/**
 * Notification settings (athletes.notification_settings). Mirrors the backend
 * (app/services/notification_prefs.py): six types with a timing option, push / email
 * per type, quiet hours, and coach texts (Photon, being replaced by push).
 * Email is stored but not sent yet.
 */
export type NotificationTypeId = 'debrief' | 'plan' | 'ready' | 'missed' | 'weekly' | 'sync';

export type NotificationTypePrefs = { on: boolean; opt?: string; push: boolean; email?: boolean };

export type NotificationPrefs = {
  v: 2;
  types: Record<NotificationTypeId, NotificationTypePrefs>;
  quiet: { on: boolean; from: string; to: string };
  texts: 'active' | 'off';
};

export const NOTIFICATION_TYPE_IDS: NotificationTypeId[] = ['debrief', 'plan', 'ready', 'missed', 'weekly', 'sync'];

/** Allowed timing options per type (value, label), as on the settings screen. */
export const NOTIFICATION_OPTIONS: Partial<Record<NotificationTypeId, { label: string; values: [string, string][] }>> = {
  debrief: { label: 'When', values: [['now', 'Right away'], ['evening', 'Evening digest · 19:00']] },
  ready: { label: 'At', values: [['06:30', '06:30'], ['07:00', '07:00'], ['07:30', '07:30'], ['08:00', '08:00']] },
  missed: { label: 'When', values: [['morning', 'Next morning'], ['evening', 'That evening · 20:00']] },
  weekly: { label: 'Day', values: [['Sun', 'Sunday 18:00'], ['Mon', 'Monday 07:00']] }
};

/** Types that can also go by email (stored; the app doesn't send notification email yet). */
export const EMAIL_CAPABLE: NotificationTypeId[] = ['plan', 'weekly', 'sync'];

export const NOTIFICATION_DEFAULTS: NotificationPrefs = {
  v: 2,
  types: {
    debrief: { on: true, opt: 'now', push: true },
    plan: { on: true, push: true, email: false },
    ready: { on: true, opt: '07:00', push: true },
    missed: { on: true, opt: 'morning', push: true },
    weekly: { on: true, opt: 'Sun', push: true, email: false },
    sync: { on: true, push: true, email: false }
  },
  quiet: { on: true, from: '22:00', to: '07:00' },
  texts: 'active'
};

const LEGACY: Record<string, NotificationTypeId[]> = {
  readiness: ['ready'],
  coach: ['debrief', 'plan'],
  workouts: ['missed'],
  insights: ['weekly']
};

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Saved settings merged over the defaults; old flat flags are read as a fallback. */
export function effectiveNotificationPrefs(raw: unknown): NotificationPrefs {
  const out: NotificationPrefs = structuredClone(NOTIFICATION_DEFAULTS);
  const saved = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  for (const [legacy, ids] of Object.entries(LEGACY)) {
    if (typeof saved[legacy] === 'boolean') for (const id of ids) out.types[id].on = saved[legacy] as boolean;
  }
  const types = (saved.types && typeof saved.types === 'object' ? saved.types : {}) as Record<string, Record<string, unknown>>;
  for (const id of NOTIFICATION_TYPE_IDS) {
    const t = types[id];
    if (!t || typeof t !== 'object') continue;
    for (const k of ['on', 'push', 'email'] as const) if (typeof t[k] === 'boolean') out.types[id][k] = t[k] as boolean;
    const opts = NOTIFICATION_OPTIONS[id]?.values.map(([v]) => v);
    if (opts && typeof t.opt === 'string' && opts.includes(t.opt)) out.types[id].opt = t.opt;
  }
  const q = saved.quiet as Record<string, unknown> | undefined;
  if (q && typeof q === 'object') {
    if (typeof q.on === 'boolean') out.quiet.on = q.on;
    if (typeof q.from === 'string' && HHMM.test(q.from)) out.quiet.from = q.from;
    if (typeof q.to === 'string' && HHMM.test(q.to)) out.quiet.to = q.to;
  }
  if (saved.texts === 'active' || saved.texts === 'off') out.texts = saved.texts;
  return out;
}

/** How many notification types are on (Me page summary). */
export function enabledNotificationCount(raw: unknown): number {
  const p = effectiveNotificationPrefs(raw);
  return NOTIFICATION_TYPE_IDS.filter((id) => p.types[id].on).length;
}
