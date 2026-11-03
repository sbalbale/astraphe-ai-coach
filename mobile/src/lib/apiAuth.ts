import { supabase } from '$lib/supabase';
import { authStore } from '$lib/stores/authStore.svelte';
import type { Session } from '@supabase/supabase-js';
import { decodeJwtPayload } from '$lib/utils/jwt';

/** Refresh slightly before expiry so in-flight requests do not 401. */
const TOKEN_REFRESH_BUFFER_MS = 60_000;
// Trimmed like authStore's copy: a stray newline in the deployed env used to make
// every session look foreign and sign the user out.
const EXPECTED_SUPABASE_URL = String(import.meta.env.VITE_SUPABASE_URL ?? '').trim();

function isAccessTokenExpired(accessToken: string): boolean {
  try {
    const payload = decodeJwtPayload(accessToken) as { exp?: number } | null;
    if (!payload || typeof payload.exp !== 'number') return true;
    return payload.exp * 1000 < Date.now() + TOKEN_REFRESH_BUFFER_MS;
  } catch {
    return true;
  }
}

function isSessionFromExpectedSupabase(session: Session): boolean {
  if (!EXPECTED_SUPABASE_URL) return false;
  try {
    const payload = decodeJwtPayload(session.access_token) as { iss?: unknown } | null;
    return !!payload && typeof payload.iss === 'string' && payload.iss.startsWith(EXPECTED_SUPABASE_URL);
  } catch {
    return false;
  }
}

// One refresh at a time: N parallel requests with an expired token each called
// refreshSession(), rotating the refresh token N times (later ones then fail).
let _refreshInFlight: ReturnType<typeof supabase.auth.refreshSession> | null = null;
function refreshSessionOnce(): ReturnType<typeof supabase.auth.refreshSession> {
  if (!_refreshInFlight) {
    _refreshInFlight = supabase.auth.refreshSession().finally(() => {
      _refreshInFlight = null;
    });
  }
  return _refreshInFlight;
}

/** Returns a valid Supabase session, refreshing when the JWT is missing or expired. */
export async function ensureAuthSession() {
  let session = authStore.session;
  if (!session?.access_token) {
    const got = await supabase.auth.getSession();
    session = got.data.session ?? null;
  }
  if (session?.access_token && !isSessionFromExpectedSupabase(session)) {
    await supabase.auth.signOut();
    authStore.session = null;
    authStore.user = null;
    return null;
  }
  if (!session?.access_token || isAccessTokenExpired(session.access_token)) {
    const { data, error } = await refreshSessionOnce();
    if (!error && data.session) {
      if (!isSessionFromExpectedSupabase(data.session)) {
        await supabase.auth.signOut();
        authStore.session = null;
        authStore.user = null;
        return null;
      }
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
