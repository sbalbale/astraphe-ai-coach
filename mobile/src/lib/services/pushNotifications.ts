import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { goto } from '$app/navigation';
import { api } from '$lib/api';
import { isStandaloneDisplayMode } from '$lib/utils/pwa';
import { isIosUserAgent } from '$lib/utils/notificationUi';
import { notificationTarget } from '$lib/utils/coachThreads';

/**
 * Request push permission without registering.
 * Returns true if granted (or already granted).
 */
export async function requestPushPermission(): Promise<boolean> {
  try {
    if (Capacitor.isNativePlatform()) {
      let status = await PushNotifications.checkPermissions();
      if (status.receive === 'denied') return false;
      if (status.receive !== 'granted') {
        status = await PushNotifications.requestPermissions();
      }
      return status.receive === 'granted';
    } else {
      if (!('Notification' in window)) return false;
      if (Notification.permission === 'denied') return false;
      if (Notification.permission !== 'granted') {
        const result = await Notification.requestPermission();
        return result === 'granted';
      }
      return true;
    }
  } catch {
    return false;
  }
}

// The token this device registered for the signed-in user, so sign-out can remove it
// (otherwise the previous user's coach notifications keep arriving on this device).
let _registered: { token: string; platform: string } | null = null;

/** Remove this device's push token from the signed-in account. Best-effort. */
export async function unregisterPushToken(): Promise<void> {
  const reg = _registered;
  _registered = null;
  if (!reg) return;
  try {
    await api.deleteJson('/v1/notifications/token', reg);
  } catch {
    // best-effort
  }
}

/** Only in-app paths (`/plan?x=1`), never absolute or protocol-relative URLs. */
export function safeNotificationPath(url: unknown): string {
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') && !url.includes('\\')
    ? url
    : '/dashboard';
}

/**
 * How web push setup ended, so the settings button can say why it didn't turn on:
 * 'ok' (subscribed and saved), 'skipped' (a browser tab without permission yet, or iOS
 * outside the Home Screen app), 'unsupported', 'not-configured' (no VAPID key in this
 * build), 'no-service-worker' (it never became ready), 'failed' (subscribe or save threw).
 */
export type PushSetupResult = 'ok' | 'skipped' | 'unsupported' | 'not-configured' | 'no-service-worker' | 'failed';

/**
 * Full push setup: request permission, register token, attach listeners.
 * Safe to call multiple times — Capacitor deduplicates listeners.
 */
export async function initPushNotifications(): Promise<PushSetupResult> {
  try {
    if (Capacitor.isNativePlatform()) {
      await _initNativePush();
      return 'ok';
    }
    return await _initWebPush();
  } catch (e) {
    console.warn('[Push] Init failed:', e);
    return 'failed';
  }
}

async function _initNativePush(): Promise<void> {
  let permStatus = await PushNotifications.checkPermissions();
  if (permStatus.receive === 'prompt') {
    permStatus = await PushNotifications.requestPermissions();
  }
  if (permStatus.receive !== 'granted') return;

  // Listeners first: a fast 'registration' event fired before the listener existed
  // was lost, and the token never reached the server.
  // Replace (not stack) listeners: this runs again for each user who signs in.
  await PushNotifications.removeAllListeners?.();
  {
    await PushNotifications.addListener('registration', async (token) => {
      const platform = Capacitor.getPlatform() as 'ios' | 'android';
      _registered = { token: token.value, platform };
      await api.post('/v1/notifications/token', _registered);
    });

    await PushNotifications.addListener('registrationError', (err) => {
      console.error('[Push] Registration error:', err.error);
    });

    // Foreground notification — just log; the OS handles lock-screen display
    await PushNotifications.addListener('pushNotificationReceived', (notification) => {
      console.log('[Push] Foreground notification:', notification.title);
    });

    // User tapped a notification
    await PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
      Promise.resolve(goto(safeNotificationPath(notificationTarget(action.notification.data)))).catch(() => {});
    });
  }

  // Re-registering re-emits 'registration', which posts the token for the *current*
  // user (a new sign-in on this device).
  await PushNotifications.register();
}

/**
 * Whether this browser currently has a web push subscription. Used by the settings
 * screen: permission alone doesn't mean notifications arrive.
 */
export async function hasWebPushSubscription(): Promise<boolean> {
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
    const reg = await Promise.race([
      navigator.serviceWorker.getRegistration(),
      new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 3000)),
    ]);
    if (!reg?.pushManager) return false;
    return (await reg.pushManager.getSubscription()) !== null;
  } catch {
    return false;
  }
}

/**
 * The push service worker (src/service-worker.ts, which caches nothing), registered here
 * because nothing else registers it. Dev serves it as an ES module. Resolves once active,
 * or null after 10 s.
 */
async function pushServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  try {
    await navigator.serviceWorker.register('/service-worker.js', {
      scope: '/',
      type: import.meta.env.DEV ? 'module' : 'classic',
    });
  } catch (e) {
    console.warn('[Push] Service worker registration failed:', e);
    return null;
  }
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 10_000)),
  ]);
}

async function _initWebPush(): Promise<PushSetupResult> {
  // iPhone/iPad: web push only exists in the Home Screen app. Elsewhere (desktop, Android)
  // a normal browser tab can subscribe.
  const standalone = isStandaloneDisplayMode();
  if (!standalone && isIosUserAgent(navigator.userAgent, navigator.maxTouchPoints ?? 0)) return 'skipped';
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return 'unsupported';

  const vapidPublicKey = String(import.meta.env.VITE_VAPID_PUBLIC_KEY ?? '').trim();
  if (!vapidPublicKey) {
    console.warn('[Push] VITE_VAPID_PUBLIC_KEY is not set; web push is off in this build.');
    return 'not-configured';
  }

  // No permission, no push: don't register the worker for nothing. In a browser tab, ask
  // only from the settings screen's button (it requests permission first); this also runs
  // on every sign-in, without a user gesture.
  if (Notification.permission === 'denied') return 'skipped';
  if (Notification.permission !== 'granted') {
    if (!standalone) return 'skipped';
    const result = await Notification.requestPermission();
    if (result !== 'granted') return 'skipped';
  }

  const reg = await pushServiceWorker();
  if (!reg?.pushManager) return 'no-service-worker';

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: _urlBase64ToUint8Array(vapidPublicKey),
    });
  }

  _registered = { token: JSON.stringify(sub.toJSON()), platform: 'web' };
  await api.post('/v1/notifications/token', _registered);
  return 'ok';
}

function _urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  return new Uint8Array([...raw].map((c) => c.charCodeAt(0)));
}
