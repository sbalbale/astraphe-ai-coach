import { supabase } from '../supabase';
import type { User, Session } from '@supabase/supabase-js';

// The expected Supabase URL for this environment
const EXPECTED_SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;

export type AccountTier = 'free' | 'trial' | 'premium';

function normalizeTier(value: unknown): AccountTier {
  const v = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (v === 'premium' || v === 'trial' || v === 'free') return v;
  return 'free';
}

class AuthState {
  user = $state<User | null>(null);
  session = $state<Session | null>(null);
  loading = $state(true);

  get tier(): AccountTier {
    // Source of truth: Supabase Auth app_metadata.tier
    // (free | trial | premium). Unknown/missing => free.
    const meta = this.user?.app_metadata as Record<string, unknown> | undefined;
    return normalizeTier(meta?.tier);
  }

  get tierLabel(): 'FREE' | 'TRIAL' | 'PREMIUM' {
    const t = this.tier;
    if (t === 'premium') return 'PREMIUM';
    if (t === 'trial') return 'TRIAL';
    return 'FREE';
  }

  constructor() {
    this.init();
  }

  private async hydrateUserFromServer() {
    // `session.user` can be stale for app_metadata; fetch the canonical user object.
    try {
      const { data, error } = await supabase.auth.getUser();
      if (!error && data?.user) this.user = data.user;
    } catch (e) {
      console.warn('[auth] Failed to hydrate user from server', e);
    }
  }

  async init() {
    // Clear stale sessions from a different Supabase project
    // (e.g. switching from hosted to local or vice versa)
    // 8s timeout prevents indefinite black screen on slow mobile networks
    const sessionRace = await Promise.race([
      supabase.auth.getSession(),
      new Promise<{ data: { session: null }; error: null }>((resolve) =>
        setTimeout(() => resolve({ data: { session: null }, error: null }), 8000)
      ),
    ]);
    const { data: { session } } = sessionRace;

    if (session) {
      // Validate the token belongs to the current project by checking the issuer
      const tokenPayload = this.parseJwt(session.access_token);
      const iss = tokenPayload?.iss;
      const issuer: string = typeof iss === 'string' ? iss : '';
      const isValidIssuer = issuer.startsWith(EXPECTED_SUPABASE_URL) ||
                            issuer.includes('127.0.0.1:57321') ||
                            EXPECTED_SUPABASE_URL.includes('supabase.co');

      if (!isValidIssuer) {
        console.warn('[auth] Stale session from different Supabase project — signing out');
        await supabase.auth.signOut();
        this.session = null;
        this.user = null;
        this.loading = false;
        return;
      }
    }

    this.session = session;
    this.user = session?.user ?? null;
    if (session) {
      await this.hydrateUserFromServer();
    }
    this.loading = false;

    // Listen to changes
    supabase.auth.onAuthStateChange(async (event, session) => {
      this.session = session;
      this.user = session?.user ?? null;
      // Skip getUser on USER_UPDATED — session.user is already fresh; concurrent getUser()
      // during updateUser() causes NavigatorLockAcquireTimeoutError in the browser.
      if (session && event !== 'USER_UPDATED') {
        await this.hydrateUserFromServer();
      }
    });
  }

  private parseJwt(token: string): Record<string, unknown> | null {
    try {
      return JSON.parse(atob(token.split('.')[1]));
    } catch {
      return null;
    }
  }

  async signOut(opts?: { timeoutMs?: number }) {
    const timeoutMs = typeof opts?.timeoutMs === 'number' && opts.timeoutMs > 0 ? opts.timeoutMs : 4000;

    // Fail-open: clear local auth state immediately so UI/guards can transition
    // even if Supabase signOut hangs or the network is flaky.
    this.session = null;
    this.user = null;

    const timeout = new Promise<never>((_, reject) => {
      const id = setTimeout(() => {
        clearTimeout(id);
        reject(new Error('signOut timeout'));
      }, timeoutMs);
    });

    try {
      await Promise.race([supabase.auth.signOut(), timeout]);
    } catch (e) {
      console.warn('[auth] signOut failed (local state already cleared)', e);
    }
  }
}

export const authStore = new AuthState();
