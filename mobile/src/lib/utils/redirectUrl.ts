import { Capacitor } from '@capacitor/core';

export function authRedirectUrl(path: 'callback' | 'reset-password'): string {
  if (Capacitor.isNativePlatform()) {
    return `astraphe://auth/${path}`;
  }
  // Web: use the current origin so it works on localhost and app.astrapheai.com
  return `${window.location.origin}/auth/${path}`;
}
