import { supabase } from '$lib/supabase';
import { authStore } from '$lib/stores/authStore.svelte';

/** Refresh slightly before expiry so in-flight requests do not 401. */
const TOKEN_REFRESH_BUFFER_MS = 60_000;

function isAccessTokenExpired(accessToken: string): boolean {
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1])) as { exp?: number };
    if (typeof payload.exp !== 'number') return true;
    return payload.exp * 1000 < Date.now() + TOKEN_REFRESH_BUFFER_MS;
  } catch {
    return true;
  }
}

/** Returns a valid Supabase session, refreshing when the JWT is missing or expired. */
export async function ensureAuthSession() {
  let session = authStore.session;
  if (!session?.access_token) {
    const got = await supabase.auth.getSession();
    session = got.data.session ?? null;
  }
  if (!session?.access_token || isAccessTokenExpired(session.access_token)) {
    const { data, error } = await supabase.auth.refreshSession();
    if (!error && data.session) {
      session = data.session;
      authStore.session = data.session;
      authStore.user = data.session.user;
    } else {
      session = null;
    }
  }
  return session;
}

export async function getAuthHeaders(
  customHeaders: Record<string, string> = {}
): Promise<Record<string, string>> {
  const session = await ensureAuthSession();
  const headers: Record<string, string> = { ...customHeaders };
  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  }
  return headers;
}
