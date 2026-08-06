import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getSessionMock = vi.fn();
const refreshSessionMock = vi.fn();
const signOutMock = vi.fn();

vi.mock('$lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => getSessionMock(...args),
      refreshSession: (...args: unknown[]) => refreshSessionMock(...args),
      signOut: (...args: unknown[]) => signOutMock(...args)
    }
  }
}));

const authStoreMock: { session: any; user: any } = { session: null, user: null };
vi.mock('$lib/stores/authStore.svelte', () => ({
  authStore: authStoreMock
}));

function makeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'none' }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.sig`;
}

// EXPECTED_SUPABASE_URL is read from import.meta.env at module load time, so each
// "expected URL" variant needs a fresh module instance loaded after vi.stubEnv().
async function loadApiAuth(supabaseUrl: string | undefined) {
  vi.resetModules();
  if (supabaseUrl === undefined) {
    vi.unstubAllEnvs();
  } else {
    vi.stubEnv('VITE_SUPABASE_URL', supabaseUrl);
  }
  return await import('./apiAuth');
}

beforeEach(() => {
  authStoreMock.session = null;
  authStoreMock.user = null;
});

afterEach(() => {
  getSessionMock.mockReset();
  refreshSessionMock.mockReset();
  signOutMock.mockReset();
  vi.unstubAllEnvs();
});

describe('ensureAuthSession (no expected supabase URL configured)', () => {
  it('an in-memory session is always treated as untrusted and signed out', async () => {
    const { ensureAuthSession } = await loadApiAuth(undefined);
    const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: 'https://anything.supabase.co' });
    authStoreMock.session = { access_token: token };
    signOutMock.mockResolvedValue({});
    const result = await ensureAuthSession();
    expect(result).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
    expect(authStoreMock.session).toBeNull();
  });

  it('fetches a session from supabase when none is cached', async () => {
    const { ensureAuthSession } = await loadApiAuth(undefined);
    getSessionMock.mockResolvedValue({ data: { session: null } });
    refreshSessionMock.mockResolvedValue({ data: { session: null }, error: { message: 'no session' } });
    const result = await ensureAuthSession();
    expect(result).toBeNull();
    expect(getSessionMock).toHaveBeenCalled();
  });
});

describe('ensureAuthSession (expected supabase URL configured)', () => {
  const EXPECTED = 'https://myproj.supabase.co';

  it('returns the in-memory session when its token is valid, unexpired, and from the expected project', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: EXPECTED });
    authStoreMock.session = { access_token: token };
    const result = await ensureAuthSession();
    expect(result?.access_token).toBe(token);
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it('signs out when the session issuer does not match the expected project', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: 'https://wrong-project.supabase.co' });
    authStoreMock.session = { access_token: token };
    signOutMock.mockResolvedValue({});
    const result = await ensureAuthSession();
    expect(result).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
    expect(authStoreMock.session).toBeNull();
    expect(authStoreMock.user).toBeNull();
  });

  it('refreshes an expired session and updates the auth store when the refreshed session matches', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    const expiredToken = makeJwt({ exp: Math.floor(Date.now() / 1000) - 10, iss: EXPECTED });
    authStoreMock.session = { access_token: expiredToken };
    const freshToken = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: EXPECTED });
    refreshSessionMock.mockResolvedValue({
      data: { session: { access_token: freshToken, user: { id: 'u1' } } },
      error: null
    });
    const result = await ensureAuthSession();
    expect(result?.access_token).toBe(freshToken);
    expect(authStoreMock.session?.access_token).toBe(freshToken);
    expect(authStoreMock.user).toEqual({ id: 'u1' });
  });

  it('signs out when the refreshed session issuer does not match', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    const expiredToken = makeJwt({ exp: Math.floor(Date.now() / 1000) - 10, iss: EXPECTED });
    authStoreMock.session = { access_token: expiredToken };
    const wrongToken = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: 'https://wrong.supabase.co' });
    refreshSessionMock.mockResolvedValue({
      data: { session: { access_token: wrongToken, user: { id: 'u1' } } },
      error: null
    });
    signOutMock.mockResolvedValue({});
    const result = await ensureAuthSession();
    expect(result).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
  });

  it('returns null when refresh fails', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    authStoreMock.session = null;
    getSessionMock.mockResolvedValue({ data: { session: null } });
    refreshSessionMock.mockResolvedValue({ data: { session: null }, error: { message: 'expired' } });
    const result = await ensureAuthSession();
    expect(result).toBeNull();
  });

  it('an unparseable JWT fails the issuer check first and signs out (never reaches refresh)', async () => {
    const { ensureAuthSession } = await loadApiAuth(EXPECTED);
    authStoreMock.session = { access_token: 'not-a-jwt' };
    signOutMock.mockResolvedValue({});
    const result = await ensureAuthSession();
    expect(result).toBeNull();
    expect(signOutMock).toHaveBeenCalled();
    expect(refreshSessionMock).not.toHaveBeenCalled();
  });
});

describe('getAuthHeaders', () => {
  it('adds an Authorization header when a session is available', async () => {
    const { getAuthHeaders } = await loadApiAuth('https://myproj.supabase.co');
    const token = makeJwt({ exp: Math.floor(Date.now() / 1000) + 3600, iss: 'https://myproj.supabase.co' });
    authStoreMock.session = { access_token: token };
    const headers = await getAuthHeaders({ 'X-Custom': '1' });
    expect(headers['X-Custom']).toBe('1');
    expect(headers['Authorization']).toBe(`Bearer ${token}`);
  });

  it('omits Authorization header when no session is available', async () => {
    const { getAuthHeaders } = await loadApiAuth(undefined);
    getSessionMock.mockResolvedValue({ data: { session: null } });
    refreshSessionMock.mockResolvedValue({ data: { session: null }, error: { message: 'no session' } });
    const headers = await getAuthHeaders();
    expect(headers['Authorization']).toBeUndefined();
  });
});
