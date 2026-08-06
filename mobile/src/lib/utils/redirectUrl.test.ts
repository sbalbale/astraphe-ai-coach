import { afterEach, describe, expect, it, vi } from 'vitest';

const isNativePlatformMock = vi.fn();
vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => isNativePlatformMock() }
}));

import { authRedirectUrl } from './redirectUrl';

afterEach(() => {
  isNativePlatformMock.mockReset();
});

describe('authRedirectUrl', () => {
  it('uses the custom scheme on native platforms', () => {
    isNativePlatformMock.mockReturnValue(true);
    expect(authRedirectUrl('callback')).toBe('astraphe://auth/callback');
    expect(authRedirectUrl('reset-password')).toBe('astraphe://auth/reset-password');
  });

  it('uses window.location.origin on web', () => {
    isNativePlatformMock.mockReturnValue(false);
    expect(authRedirectUrl('callback')).toBe(`${window.location.origin}/auth/callback`);
  });
});
