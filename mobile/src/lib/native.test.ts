import { afterEach, describe, expect, it, vi } from 'vitest';

const addListenerMock = vi.fn();
const requestPermissionsMock = vi.fn();
const dispatchEventMock = vi.fn();
const preferencesSetMock = vi.fn();
const preferencesGetMock = vi.fn();

vi.mock('@capacitor/app', () => ({
  App: { addListener: (...args: unknown[]) => addListenerMock(...args) }
}));
vi.mock('@capacitor/preferences', () => ({
  Preferences: {
    set: (...args: unknown[]) => preferencesSetMock(...args),
    get: (...args: unknown[]) => preferencesGetMock(...args)
  }
}));
vi.mock('@capacitor/background-runner', () => ({
  BackgroundRunner: {
    requestPermissions: (...args: unknown[]) => requestPermissionsMock(...args),
    dispatchEvent: (...args: unknown[]) => dispatchEventMock(...args)
  }
}));

import { cacheData, getCachedData, setupNativeIntegrations } from './native';

afterEach(() => {
  addListenerMock.mockReset();
  requestPermissionsMock.mockReset();
  dispatchEventMock.mockReset();
  preferencesSetMock.mockReset();
  preferencesGetMock.mockReset();
});

describe('setupNativeIntegrations', () => {
  it('registers the deep-link listener and dispatches the background sync event', async () => {
    requestPermissionsMock.mockResolvedValue(undefined);
    dispatchEventMock.mockResolvedValue(undefined);
    await setupNativeIntegrations();
    expect(addListenerMock).toHaveBeenCalledWith('appUrlOpen', expect.any(Function));
    expect(requestPermissionsMock).toHaveBeenCalled();
    expect(dispatchEventMock).toHaveBeenCalled();
  });

  it('the appUrlOpen listener handles an astraphe://connected URL without throwing', async () => {
    requestPermissionsMock.mockResolvedValue(undefined);
    dispatchEventMock.mockResolvedValue(undefined);
    await setupNativeIntegrations();
    const handler = addListenerMock.mock.calls[0][1] as (data: { url: string }) => void;
    expect(() => handler({ url: 'astraphe://connected?provider=whoop' })).not.toThrow();
    expect(() => handler({ url: 'https://example.com/other' })).not.toThrow();
  });

  it('swallows background runner permission/dispatch failures', async () => {
    requestPermissionsMock.mockRejectedValue(new Error('denied'));
    await expect(setupNativeIntegrations()).resolves.toBeUndefined();
  });
});

describe('cacheData / getCachedData', () => {
  it('stores JSON-serialized data', async () => {
    preferencesSetMock.mockResolvedValue(undefined);
    await cacheData('key1', { a: 1 });
    expect(preferencesSetMock).toHaveBeenCalledWith({ key: 'key1', value: JSON.stringify({ a: 1 }) });
  });

  it('retrieves and parses stored data', async () => {
    preferencesGetMock.mockResolvedValue({ value: JSON.stringify({ a: 1 }) });
    const result = await getCachedData('key1');
    expect(result).toEqual({ a: 1 });
  });

  it('returns null when nothing stored', async () => {
    preferencesGetMock.mockResolvedValue({ value: null });
    const result = await getCachedData('missing');
    expect(result).toBeNull();
  });
});
