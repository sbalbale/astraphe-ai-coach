/**
 * Display rules for the Notification settings screen (design: NotifPrefs). Pure, so the
 * permission states, channel rules and copy can be tested without a browser.
 */
import {
  EMAIL_CAPABLE,
  type NotificationPrefs,
  type NotificationTypeId
} from '$lib/notificationSettings';
import type { PushSetupResult } from '$lib/services/pushNotifications';

export type PermissionState = 'install' | 'default' | 'denied' | 'granted' | 'unsupported';

export type PermissionEnv = {
  /** Native Capacitor shell (iOS/Android app). */
  native: boolean;
  /** Result of the native permission check, when native. */
  nativeStatus?: 'granted' | 'denied' | 'prompt' | null;
  /** `Notification.permission` in the browser, or null when the API is missing. */
  webPermission: NotificationPermission | null;
  /** iPhone / iPad browser (web push only works from the Home Screen icon there). */
  ios: boolean;
  /** Opened as an installed PWA (display-mode standalone). */
  standalone: boolean;
  /** The browser has `PushManager` (web push). Defaults to true. */
  pushManager?: boolean;
  /** This browser has a push subscription (`pushManager.getSubscription()`). */
  subscribed?: boolean;
};

/**
 * Which permission card to show. On the web, "on" needs an actual push subscription:
 * permission granted without one shows 'default', whose button subscribes again.
 */
export function permissionState(env: PermissionEnv): PermissionState {
  if (env.native) {
    if (env.nativeStatus === 'granted') return 'granted';
    if (env.nativeStatus === 'denied') return 'denied';
    return 'default';
  }
  // iOS Safari only exposes web push to Home Screen apps; in a tab the API is missing.
  // Other browsers (desktop, Android) can subscribe from a normal tab.
  if (env.ios && !env.standalone) return 'install';
  if (env.webPermission === null || env.pushManager === false) return 'unsupported';
  if (env.webPermission === 'denied') return 'denied';
  if (env.webPermission === 'granted' && env.subscribed) return 'granted';
  return 'default';
}

/**
 * After "Turn on notifications" when the permission wasn't granted. A blocked permission
 * gets its own card ('denied'), so no message; still 'default' means the prompt was
 * dismissed or the browser silently held it back (Chrome's quiet prompt).
 */
export function permissionNotGrantedMessage(webPermission: NotificationPermission | null): string | null {
  if (webPermission === 'default') {
    return "Your browser didn't turn notifications on. If no prompt appeared, click the icon at the left of the address bar, set Notifications to Allow, then try again.";
  }
  return null;
}

/** After permission was granted: why push still isn't on, or null when it worked. */
export function enablePushMessage(result: PushSetupResult): string | null {
  switch (result) {
    case 'ok':
    case 'skipped':
      return null;
    case 'not-configured':
      return "Push isn't set up for this version of Astraphe yet.";
    case 'no-service-worker':
      return "Astraphe's background worker didn't start, so push can't be set up. Reload the page and try again.";
    case 'unsupported':
      return "This browser can't receive push notifications.";
    default:
      return "Couldn't turn on push. Check your connection and try again.";
  }
}

export function isIosUserAgent(ua: string, maxTouchPoints = 0): boolean {
  // iPadOS 13+ reports a Mac user agent; touch points give it away.
  return /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && maxTouchPoints > 1);
}

/** "this iPhone", "this iPad", "this Android phone", "this browser". */
export function deviceLabel(ua: string, maxTouchPoints = 0, native = false): string {
  if (/iPad/i.test(ua) || (/Macintosh/i.test(ua) && maxTouchPoints > 1)) return 'this iPad';
  if (/iPhone|iPod/i.test(ua)) return 'this iPhone';
  if (/Android/i.test(ua)) return native ? 'this phone' : 'this Android browser';
  return native ? 'this device' : 'this browser';
}

/** Second line of the "Push is on" card from the device count (null while unknown). */
export function devicesLine(count: number | null): string {
  if (count === null) return 'Debriefs, readiness and plan changes arrive here.';
  if (count <= 1) return 'This is the only device getting your notifications.';
  return `Notifications go to ${count} devices signed in to your account, including this one.`;
}

export type TypeMeta = { id: NotificationTypeId; group: string; name: string; desc: string; opens: string };

/** Rows in screen order, grouped as in the design. */
export const TYPE_META: TypeMeta[] = [
  { id: 'debrief', group: 'COACH', name: 'Post-workout debrief', desc: 'A short note from your coach after each synced workout. Reply right in the chat.', opens: 'Coach chat for that workout' },
  { id: 'plan', group: 'COACH', name: 'Plan changed by your coach', desc: 'When a session is moved, swapped or shortened for you.', opens: 'The changed session' },
  { id: 'ready', group: 'DAILY', name: 'Morning readiness', desc: 'Your readiness score with today’s session.', opens: 'Readiness' },
  { id: 'weekly', group: 'SUMMARIES', name: 'Weekly summary', desc: 'Load, form and sleep for the week, with what’s next.', opens: 'Trends' },
  { id: 'sync', group: 'ACCOUNT', name: 'Sync problems', desc: 'When Garmin or WHOOP disconnects or stops sending data.', opens: 'Connected apps' }
];

export function groupedTypes(): { name: string; rows: TypeMeta[] }[] {
  const out: { name: string; rows: TypeMeta[] }[] = [];
  for (const t of TYPE_META) {
    let g = out.find((x) => x.name === t.group);
    if (!g) out.push((g = { name: t.group, rows: [] }));
    g.rows.push(t);
  }
  return out;
}

export function emailCapable(id: NotificationTypeId): boolean {
  return EMAIL_CAPABLE.includes(id);
}

/**
 * Prefs after tapping a channel, or null when nothing changes. Push is the only channel
 * that delivers (email isn't sent yet, so its chip is "coming soon" and does nothing).
 * Turning push off therefore turns the type off rather than leaving it on with nothing
 * delivered; a type saved with push off gets push back.
 */
export function toggleChannel(prefs: NotificationPrefs, id: NotificationTypeId, channel: 'push' | 'email'): NotificationPrefs | null {
  if (channel === 'email') return null;
  const cur = prefs.types[id];
  return withType(prefs, id, cur.push ? { on: false, push: true } : { push: true });
}

/** Switch a type on or off. Turning it on also turns push on (the channel that delivers). */
export function toggleType(prefs: NotificationPrefs, id: NotificationTypeId): NotificationPrefs {
  const on = !prefs.types[id].on;
  return withType(prefs, id, on ? { on, push: true } : { on });
}

export function withType(prefs: NotificationPrefs, id: NotificationTypeId, patch: Partial<NotificationPrefs['types'][NotificationTypeId]>): NotificationPrefs {
  return { ...prefs, types: { ...prefs.types, [id]: { ...prefs.types[id], ...patch } } };
}

export function quietNote(prefs: NotificationPrefs): string {
  const q = prefs.quiet;
  if (!q.on) return 'Off. Notifications can arrive at any time.';
  return `Nothing arrives between ${q.from} and ${q.to}. Anything due waits until ${q.to}.`;
}

/** Test button result → status line (null = nothing to show). */
export function testResultMessage(status: 'sent' | 'no_devices' | 'rate_limited' | 'error' | null, device: string): { text: string; ok: boolean } | null {
  switch (status) {
    case 'sent':
      return { text: `Sent just now to ${device === 'this browser' ? 'your devices' : device}. It should arrive in a few seconds.`, ok: true };
    case 'no_devices':
      return { text: 'No device is registered for push yet. Turn on notifications above, then try again.', ok: false };
    case 'rate_limited':
      return { text: 'A test was just sent. Wait a few seconds before sending another.', ok: false };
    case 'error':
      return { text: "Couldn't send the test. Check your connection and try again.", ok: false };
    default:
      return null;
  }
}
