import { supabase } from '$lib/supabase';

export type AuthLinkTarget = '/auth/callback' | '/auth/reset-password';

/** Which auth screen an astraphe:// or https link is for, or null if it isn't one. */
export function authLinkTarget(url: URL): AuthLinkTarget | null {
  const path = url.host === 'auth' ? url.pathname : url.pathname.replace(/^\/auth/, '');
  if (path.startsWith('/callback')) return '/auth/callback';
  if (path.startsWith('/reset-password')) return '/auth/reset-password';
  return null;
}

/**
 * Turn an auth deep link into a session. PKCE links carry ?code= (exchanged with the
 * verifier this app stored); links from emails sent before the switch carry the
 * tokens in the fragment. Returns false if the link held nothing usable.
 */
export async function sessionFromAuthLink(url: URL): Promise<boolean> {
  const code = url.searchParams.get('code');
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    return !error;
  }
  const hash = new URLSearchParams(url.hash.replace(/^#/, ''));
  const access_token = hash.get('access_token');
  const refresh_token = hash.get('refresh_token');
  if (access_token && refresh_token) {
    const { error } = await supabase.auth.setSession({ access_token, refresh_token });
    return !error;
  }
  return false;
}
