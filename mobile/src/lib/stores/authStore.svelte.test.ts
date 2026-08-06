import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const onAuthStateChangeMock = vi.fn();
const getSessionMock = vi.fn();
const getUserMock = vi.fn();
const signOutMock = vi.fn();
vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      onAuthStateChange: (...args: unknown[]) => onAuthStateChangeMock(...args),
      getSession: (...args: unknown[]) => getSessionMock(...args),
      getUser: (...args: unknown[]) => getUserMock(...args),
      signOut: (...args: unknown[]) => signOutMock(...args)
    }
  }
}));

function makeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'none' }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.sig`;
}

const EXPECTED = 'https://myproj.supabase.co';

function makeSession(overrides: Record<string, unknown> = {}) {
  const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: EXPECTED });
  return {
    access_token: token,
    user: { id: 'u1', app_metadata: {} },
    ...overrides
  };
}

async function freshAuthStore(supabaseUrl: string | undefined = EXPECTED) {
  vi.resetModules();
  if (supabaseUrl === undefined) {
    vi.unstubAllEnvs();
  } else {
    vi.stubEnv('VITE_SUPABASE_URL', supabaseUrl);
  }
  const mod = await import('./authStore.svelte');
  return mod.authStore;
}

beforeEach(() => {
  onAuthStateChangeMock.mockReset();
  getSessionMock.mockReset();
  getUserMock.mockReset();
  signOutMock.mockReset();
  // Sensible defaults so a fresh module's constructor-triggered init() never hangs
  // or throws unexpectedly before a given test overrides them.
  getSessionMock.mockResolvedValue({ data: { session: null }, error: null });
  getUserMock.mockResolvedValue({ data: { user: null }, error: null });
  signOutMock.mockResolvedValue({ error: null });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('init (constructor-triggered)', () => {
  it('registers an onAuthStateChange listener', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(onAuthStateChangeMock).toHaveBeenCalledWith(expect.any(Function));
  });

  it('no session leaves user/session null and clears loading', async () => {
    getSessionMock.mockResolvedValue({ data: { session: null } });
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
  });

  it('a valid, correctly-issued session is applied and hydrated from the server', async () => {
    const session = makeSession();
    getSessionMock.mockResolvedValue({ data: { session } });
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1', app_metadata: { tier: 'premium' } } } });
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.session?.access_token).toBe(session.access_token);
    await vi.waitFor(() => expect(store.user?.app_metadata?.tier).toBe('premium'));
  });

  it('a session with a mismatched issuer is signed out', async () => {
    const badSession = makeSession({
      access_token: makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: 'https://wrong.supabase.co' })
    });
    getSessionMock.mockResolvedValue({ data: { session: badSession } });
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
  });

  it('swallows an init failure and clears loading', async () => {
    getSessionMock.mockRejectedValue(new Error('network down'));
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
  });

  it('the onAuthStateChange callback updates session/user and hydrates on non-USER_UPDATED events', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const callback = onAuthStateChangeMock.mock.calls[0][0] as (event: string, session: unknown) => void;
    const session = makeSession();
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1', app_metadata: { tier: 'trial' } } } });
    callback('SIGNED_IN', session);
    expect(store.session?.access_token).toBe(session.access_token);
    await vi.waitFor(() => expect(store.user?.app_metadata?.tier).toBe('trial'));
  });

  it('the onAuthStateChange callback skips hydration on USER_UPDATED', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const callback = onAuthStateChangeMock.mock.calls[0][0] as (event: string, session: unknown) => void;
    getUserMock.mockClear();
    const session = makeSession();
    callback('USER_UPDATED', session);
    expect(store.session?.access_token).toBe(session.access_token);
    expect(getUserMock).not.toHaveBeenCalled();
  });

  it('the onAuthStateChange callback with a null session clears state', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const callback = onAuthStateChangeMock.mock.calls[0][0] as (event: string, session: unknown) => void;
    callback('SIGNED_OUT', null);
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
  });
});

describe('tier / tierLabel', () => {
  it('defaults to free with no user', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.tier).toBe('free');
    expect(store.tierLabel).toBe('FREE');
  });

  it('reads premium/trial/free from app_metadata.tier', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    store.user = { app_metadata: { tier: 'premium' } } as any;
    expect(store.tier).toBe('premium');
    expect(store.tierLabel).toBe('PREMIUM');
    store.user = { app_metadata: { tier: 'TRIAL' } } as any;
    expect(store.tier).toBe('trial');
    expect(store.tierLabel).toBe('TRIAL');
  });

  it('normalizes unknown/non-string tier values to free', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    store.user = { app_metadata: { tier: 'unlimited' } } as any;
    expect(store.tier).toBe('free');
    store.user = { app_metadata: { tier: 42 } } as any;
    expect(store.tier).toBe('free');
  });
});

describe('applySession', () => {
  it('sets session and user, and hydrates from the server', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const session = makeSession();
    getUserMock.mockResolvedValue({ data: { user: { id: 'u1', app_metadata: { tier: 'premium' } } } });
    store.applySession(session as any);
    expect(store.session?.access_token).toBe(session.access_token);
    expect(store.user?.id).toBe('u1');
    await vi.waitFor(() => expect(store.user?.app_metadata?.tier).toBe('premium'));
  });

  it('a null session clears state without hydrating', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    getUserMock.mockClear();
    store.applySession(null);
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
    expect(getUserMock).not.toHaveBeenCalled();
  });

  it('hydrateUserFromServer logs and keeps the session-derived user on a getUser error', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const session = makeSession({ user: { id: 'u1', app_metadata: { tier: 'free' } } });
    getUserMock.mockResolvedValue({ data: { user: null }, error: { message: 'server error' } });
    store.applySession(session as any);
    await vi.waitFor(() => expect(getUserMock).toHaveBeenCalled());
    expect(store.user?.id).toBe('u1'); // unchanged -- server call errored
  });

  it('hydrateUserFromServer swallows a thrown error', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const session = makeSession();
    getUserMock.mockRejectedValue(new Error('boom'));
    expect(() => store.applySession(session as any)).not.toThrow();
  });
});

describe('refreshSession', () => {
  it('applies a known session directly without calling getSession', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    getSessionMock.mockClear();
    const session = makeSession();
    const result = await store.refreshSession(session as any);
    expect(result).toBe(session);
    expect(store.session?.access_token).toBe(session.access_token);
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it('fetches and applies the session from supabase when no known session is given', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    const session = makeSession();
    getSessionMock.mockResolvedValue({ data: { session }, error: null });
    const result = await store.refreshSession();
    expect(result?.access_token).toBe(session.access_token);
  });

  it('clears state and returns null on a getSession error', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    getSessionMock.mockResolvedValue({ data: { session: null }, error: { message: 'expired' } });
    const result = await store.refreshSession();
    expect(result).toBeNull();
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
  });

  it('returns null and swallows a thrown error', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    getSessionMock.mockRejectedValue(new Error('network down'));
    const result = await store.refreshSession();
    expect(result).toBeNull();
  });
});

describe('signOut', () => {
  it('clears state immediately and calls supabase signOut', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    store.session = makeSession() as any;
    store.user = { id: 'u1' } as any;
    signOutMock.mockResolvedValue({ error: null });
    await store.signOut();
    expect(store.session).toBeNull();
    expect(store.user).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
  });

  it('swallows a rejected supabase signOut (state already cleared)', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    signOutMock.mockRejectedValue(new Error('network down'));
    await expect(store.signOut()).resolves.toBeUndefined();
    expect(store.session).toBeNull();
  });

  it('accepts a custom timeout option without throwing', async () => {
    const store = await freshAuthStore();
    await vi.waitFor(() => expect(store.loading).toBe(false));
    signOutMock.mockResolvedValue({ error: null });
    await expect(store.signOut({ timeoutMs: 100 })).resolves.toBeUndefined();
  });
});
