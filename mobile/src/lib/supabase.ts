import { createClient } from '@supabase/supabase-js';

const supabaseUrl     = import.meta.env.VITE_SUPABASE_URL     || 'https://placeholder.supabase.co';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY
  || import.meta.env.VITE_SUPABASE_KEY
  || 'placeholder-key';

// On iOS/Android native runtimes, route auth storage through the Capacitor
// Preferences plugin so tokens land in the iOS Keychain / Android Keystore
// instead of the WebView's unencrypted localStorage.
//
// Guards:
//   - `typeof window === 'undefined'`  → SSR / Node.js build step, skip entirely
//   - `Capacitor.isNativePlatform()`   → web browser gets undefined (uses localStorage default)
//   - try/catch                         → if Capacitor packages fail to load, fall back silently
async function buildNativeStorage() {
  if (typeof window === 'undefined') return undefined;
  try {
    const { Capacitor } = await import('@capacitor/core');
    if (!Capacitor.isNativePlatform()) return undefined;
    const { Preferences } = await import('@capacitor/preferences');
    return {
      getItem:    (key: string) => Preferences.get({ key }).then(r => r.value),
      setItem:    (key: string, value: string) => Preferences.set({ key, value }).then(() => {}),
      removeItem: (key: string) => Preferences.remove({ key }).then(() => {}),
    };
  } catch {
    return undefined;
  }
}

const nativeStorage = await buildNativeStorage();

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    ...(nativeStorage ? { storage: nativeStorage } : {}),
    persistSession: true,
    autoRefreshToken: true,
  },
});
