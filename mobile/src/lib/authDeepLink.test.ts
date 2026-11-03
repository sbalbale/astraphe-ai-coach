import { beforeEach, describe, expect, it, vi } from 'vitest';

const authMock = vi.hoisted(() => ({
  exchangeCodeForSession: vi.fn(),
  setSession: vi.fn()
}));
vi.mock('$lib/supabase', () => ({ supabase: { auth: authMock } }));

import { authLinkTarget, sessionFromAuthLink } from './authDeepLink';

beforeEach(() => {
  authMock.exchangeCodeForSession.mockReset().mockResolvedValue({ error: null });
  authMock.setSession.mockReset().mockResolvedValue({ error: null });
});

describe('auth deep links', () => {
  it('routes astraphe:// and https auth links', () => {
    expect(authLinkTarget(new URL('astraphe://auth/callback?code=x'))).toBe('/auth/callback');
    expect(authLinkTarget(new URL('astraphe://auth/reset-password?code=x'))).toBe('/auth/reset-password');
    expect(authLinkTarget(new URL('https://app.astrapheai.com/auth/callback#a=1'))).toBe('/auth/callback');
    expect(authLinkTarget(new URL('astraphe://connected?provider=whoop'))).toBeNull();
  });

  it('exchanges a PKCE code for a session', async () => {
    await expect(sessionFromAuthLink(new URL('astraphe://auth/callback?code=abc'))).resolves.toBe(true);
    expect(authMock.exchangeCodeForSession).toHaveBeenCalledWith('abc');
  });

  it('still accepts fragment tokens from emails sent before PKCE', async () => {
    const url = new URL('astraphe://auth/reset-password#access_token=AT&refresh_token=RT&type=recovery');
    await expect(sessionFromAuthLink(url)).resolves.toBe(true);
    expect(authMock.setSession).toHaveBeenCalledWith({ access_token: 'AT', refresh_token: 'RT' });
  });

  it('reports links without credentials', async () => {
    await expect(sessionFromAuthLink(new URL('astraphe://auth/callback'))).resolves.toBe(false);
  });
});
