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

  /** Sync store from Supabase after sign-in / sign-up (before layout auth guards run). */
  async refreshSession(): Promise<Session | null> {
    try {
      const { data, error } = await supabase.auth.getSession();
      if (error) {
        console.warn('[auth] refreshSession:', error.message);
        this.session = null;
        this.user = null;
        return null;
      }
      const session = data.session;
      this.session = session;
      this.user = session?.user ?? null;
      if (session) {
        await this.hydrateUserFromServer();
      }
      return session;
    } catch (e) {
      console.warn('[auth] refreshSession failed', e);
      return null;
    }
  }

  private async hydrateUserFromServer() {
    // `session.user` can be stale for app_metadata; fetch the canonical user object.
    try {
      const result = await Promise.race([
        supabase.auth.getUser(),
        new Promise<{ data: { user: null }; error: { message: string } }>((resolve) =>
          setTimeout(
            () => resolve({ data: { user: null }, error: { message: 'getUser timeout' } }),
            8000
          )
        ),
      ]);
      const { data, error } = result;
      if (!error && data?.user) this.user = data.user;
      else if (error) console.warn('[auth] hydrateUserFromServer:', error.message);
    } catch (e) {
      console.warn('[auth] Failed to hydrate user from server', e);
    }
  }

  async init() {
    supabase.auth.onAuthStateChange(async (event, session) => {
      this.session = session;
      this.user = session?.user ?? null;
      if (session && event !== 'USER_UPDATED') {
        await this.hydrateUserFromServer();
      }
    });

    try {
      const sessionRace = await Promise.race([
        supabase.auth.getSession(),
        new Promise<{ data: { session: null }; error: null }>((resolve) =>
          setTimeout(() => resolve({ data: { session: null }, error: null }), 12000)
        ),
      ]);
      const { data: { session } } = sessionRace;

      if (session) {
        const tokenPayload = this.parseJwt(session.access_token);
        const iss = tokenPayload?.iss;
        const issuer: string = typeof iss === 'string' ? iss : '';
        const isValidIssuer =
          issuer.startsWith(EXPECTED_SUPABASE_URL) ||
          issuer.includes('127.0.0.1:57321');

        if (!isValidIssuer) {
          console.warn('[auth] Stale session from different Supabase project — signing out');
          await supabase.auth.signOut();
          this.session = null;
          this.user = null;
          return;
        }
      }

      this.session = session;
      this.user = session?.user ?? null;
      if (session) {
        await this.hydrateUserFromServer();
      }
    } catch (e) {
      console.warn('[auth] init failed', e);
      this.session = null;
      this.user = null;
    } finally {
      this.loading = false;
    }
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
