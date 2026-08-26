import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { goto } from '$app/navigation';
import { api } from '$lib/api';
import { isStandaloneDisplayMode } from '$lib/utils/pwa';

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

/**
 * Full push setup: request permission, register token, attach listeners.
 * Safe to call multiple times — Capacitor deduplicates listeners.
 */
export async function initPushNotifications(): Promise<void> {
  try {
    if (Capacitor.isNativePlatform()) {
      await _initNativePush();
    } else {
      await _initWebPush();
    }
  } catch (e) {
    console.warn('[Push] Init failed:', e);
  }
}

async function _initNativePush(): Promise<void> {
  let permStatus = await PushNotifications.checkPermissions();
  if (permStatus.receive === 'prompt') {
    permStatus = await PushNotifications.requestPermissions();
  }
  if (permStatus.receive !== 'granted') return;

  await PushNotifications.register();

  await PushNotifications.addListener('registration', async (token) => {
    const platform = Capacitor.getPlatform() as 'ios' | 'android';
    await api.post('/v1/notifications/token', { token: token.value, platform });
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
    const url = (action.notification.data?.url as string | undefined) ?? '/dashboard';
    goto(url);
  });
}

async function _initWebPush(): Promise<void> {
  if (!isStandaloneDisplayMode()) return;
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

  const vapidPublicKey = (import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined) ?? '';
  if (!vapidPublicKey) return;

  const reg = await Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 8000)),
  ]);
  if (!reg?.pushManager) return;

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    if (Notification.permission === 'denied') return;
    if (Notification.permission !== 'granted') {
      const result = await Notification.requestPermission();
      if (result !== 'granted') return;
    }
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: _urlBase64ToUint8Array(vapidPublicKey),
    });
  }

  await api.post('/v1/notifications/token', {
    token: JSON.stringify(sub.toJSON()),
    platform: 'web',
  });
}

function _urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  return new Uint8Array([...raw].map((c) => c.charCodeAt(0)));
}
