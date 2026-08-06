import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const isNativePlatformMock = vi.fn();
const getPlatformMock = vi.fn(() => 'ios');
const requestAuthorizationMock = vi.fn();
vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: () => isNativePlatformMock(),
    getPlatform: () => getPlatformMock()
  }
}));
vi.mock('@interval-health/capacitor-health', () => ({
  Health: { requestAuthorization: (...args: unknown[]) => requestAuthorizationMock(...args) }
}));

const apiPostMock = vi.fn();
vi.mock('../api', () => ({
  api: { post: (...args: unknown[]) => apiPostMock(...args) }
}));

import { HealthIntegration } from './health';

beforeEach(() => {
  isNativePlatformMock.mockReset();
  requestAuthorizationMock.mockReset();
  apiPostMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('HealthIntegration.isAvailable', () => {
  it('mirrors Capacitor.isNativePlatform', () => {
    isNativePlatformMock.mockReturnValue(true);
    expect(HealthIntegration.isAvailable()).toBe(true);
    isNativePlatformMock.mockReturnValue(false);
    expect(HealthIntegration.isAvailable()).toBe(false);
  });
});

describe('HealthIntegration.requestPermissions', () => {
  it('simulates success on the web', async () => {
    isNativePlatformMock.mockReturnValue(false);
    expect(await HealthIntegration.requestPermissions()).toBe(true);
  });

  it('requests native authorization and returns true on success', async () => {
    isNativePlatformMock.mockReturnValue(true);
    requestAuthorizationMock.mockResolvedValue(undefined);
    expect(await HealthIntegration.requestPermissions()).toBe(true);
    expect(requestAuthorizationMock).toHaveBeenCalledWith({
      read: ['sleep', 'heartRate', 'workout'],
      write: []
    });
  });

  it('returns false when native authorization throws', async () => {
    isNativePlatformMock.mockReturnValue(true);
    requestAuthorizationMock.mockRejectedValue(new Error('denied'));
    expect(await HealthIntegration.requestPermissions()).toBe(false);
  });
});

describe('HealthIntegration.syncRecentData', () => {
  it('posts a mock-synced payload on the web', async () => {
    isNativePlatformMock.mockReturnValue(false);
    apiPostMock.mockResolvedValue({ ok: true });
    await HealthIntegration.syncRecentData();
    expect(apiPostMock).toHaveBeenCalledWith('/v1/biometrics/sync', { status: 'mock_synced' });
  });

  it('posts a native payload with device platform', async () => {
    isNativePlatformMock.mockReturnValue(true);
    getPlatformMock.mockReturnValue('ios');
    apiPostMock.mockResolvedValue({ ok: true });
    const payload = await HealthIntegration.syncRecentData();
    expect(apiPostMock).toHaveBeenCalledWith(
      '/v1/biometrics/sync',
      expect.objectContaining({ device: 'ios', data: [] })
    );
    expect(payload?.device).toBe('ios');
  });

  it('rethrows when the native sync path fails', async () => {
    isNativePlatformMock.mockReturnValue(true);
    apiPostMock.mockRejectedValue(new Error('network down'));
    await expect(HealthIntegration.syncRecentData()).rejects.toThrow('network down');
  });
});
