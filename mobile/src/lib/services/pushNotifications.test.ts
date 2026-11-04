import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const isNativePlatformMock = vi.fn();
const getPlatformMock = vi.fn(() => 'ios');
vi.mock('@capacitor/core', () => ({
  Capacitor: {
    isNativePlatform: () => isNativePlatformMock(),
    getPlatform: () => getPlatformMock()
  }
}));

const checkPermissionsMock = vi.fn();
const requestPermissionsMock = vi.fn();
const registerMock = vi.fn();
const addListenerMock = vi.fn();
vi.mock('@capacitor/push-notifications', () => ({
  PushNotifications: {
    checkPermissions: (...args: unknown[]) => checkPermissionsMock(...args),
    requestPermissions: (...args: unknown[]) => requestPermissionsMock(...args),
    register: (...args: unknown[]) => registerMock(...args),
    addListener: (...args: unknown[]) => addListenerMock(...args)
  }
}));

const gotoMock = vi.fn();
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => gotoMock(...args) }));

const apiPostMock = vi.fn();
vi.mock('$lib/api', () => ({ api: { post: (...args: unknown[]) => apiPostMock(...args) } }));

const isStandaloneMock = vi.fn();
vi.mock('$lib/utils/pwa', () => ({ isStandaloneDisplayMode: () => isStandaloneMock() }));

import { hasWebPushSubscription, initPushNotifications, requestPushPermission } from './pushNotifications';

beforeEach(() => {
  isNativePlatformMock.mockReset();
  getPlatformMock.mockReturnValue('ios');
  checkPermissionsMock.mockReset();
  requestPermissionsMock.mockReset();
  registerMock.mockReset().mockResolvedValue(undefined);
  addListenerMock.mockReset().mockResolvedValue(undefined);
  gotoMock.mockReset();
  apiPostMock.mockReset().mockResolvedValue({ ok: true });
  isStandaloneMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('requestPushPermission (native)', () => {
  beforeEach(() => isNativePlatformMock.mockReturnValue(true));

  it('denied status returns false without requesting', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'denied' });
    expect(await requestPushPermission()).toBe(false);
    expect(requestPermissionsMock).not.toHaveBeenCalled();
  });

  it('already granted returns true without requesting', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
    expect(await requestPushPermission()).toBe(true);
    expect(requestPermissionsMock).not.toHaveBeenCalled();
  });

  it('prompt status requests permission and reflects the result', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'prompt' });
    requestPermissionsMock.mockResolvedValue({ receive: 'granted' });
    expect(await requestPushPermission()).toBe(true);
    expect(requestPermissionsMock).toHaveBeenCalled();
  });

  it('swallows thrown errors and returns false', async () => {
    checkPermissionsMock.mockRejectedValue(new Error('native error'));
    expect(await requestPushPermission()).toBe(false);
  });
});

describe('requestPushPermission (web)', () => {
  beforeEach(() => isNativePlatformMock.mockReturnValue(false));

  it('false when Notification API is unavailable', async () => {
    const original = (window as any).Notification;
    delete (window as any).Notification;
    expect(await requestPushPermission()).toBe(false);
    (window as any).Notification = original;
  });

  it('false when permission is denied', async () => {
    vi.stubGlobal('Notification', { permission: 'denied', requestPermission: vi.fn() });
    expect(await requestPushPermission()).toBe(false);
  });

  it('true when already granted', async () => {
    vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
    expect(await requestPushPermission()).toBe(true);
  });

  it('requests permission when default and reflects the result', async () => {
    const requestPermission = vi.fn().mockResolvedValue('granted');
    vi.stubGlobal('Notification', { permission: 'default', requestPermission });
    expect(await requestPushPermission()).toBe(true);
    expect(requestPermission).toHaveBeenCalled();
  });
});

describe('initPushNotifications (native)', () => {
  beforeEach(() => isNativePlatformMock.mockReturnValue(true));

  it('stops after checkPermissions if not granted after prompting', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'prompt' });
    requestPermissionsMock.mockResolvedValue({ receive: 'denied' });
    await initPushNotifications();
    expect(registerMock).not.toHaveBeenCalled();
  });

  it('registers and wires up all listeners when granted', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
    await initPushNotifications();
    expect(registerMock).toHaveBeenCalled();
    expect(addListenerMock).toHaveBeenCalledTimes(4);
    const events = addListenerMock.mock.calls.map((c) => c[0]);
    expect(events).toEqual([
      'registration',
      'registrationError',
      'pushNotificationReceived',
      'pushNotificationActionPerformed'
    ]);
  });

  it('the registration listener posts the token and platform', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
    await initPushNotifications();
    const registrationHandler = addListenerMock.mock.calls.find((c) => c[0] === 'registration')![1];
    await registrationHandler({ value: 'tok123' });
    expect(apiPostMock).toHaveBeenCalledWith('/v1/notifications/token', { token: 'tok123', platform: 'ios' });
  });

  it('the registrationError listener logs without throwing', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
    await initPushNotifications();
    const errorHandler = addListenerMock.mock.calls.find((c) => c[0] === 'registrationError')![1];
    expect(() => errorHandler({ error: 'boom' })).not.toThrow();
  });

  it('the pushNotificationReceived listener logs without throwing', async () => {
    checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
    await initPushNotifications();
    const receivedHandler = addListenerMock.mock.calls.find((c) => c[0] === 'pushNotificationReceived')![1];
    expect(() => receivedHandler({ title: 'Hi' })).not.toThrow();
  });

  it('the pushNotificationActionPerformed listener navigates to the notification url', () => {
    return (async () => {
      checkPermissionsMock.mockResolvedValue({ receive: 'granted' });
      await initPushNotifications();
      const actionHandler = addListenerMock.mock.calls.find(
        (c) => c[0] === 'pushNotificationActionPerformed'
      )![1];
      actionHandler({ notification: { data: { url: '/workouts/1' } } });
      expect(gotoMock).toHaveBeenCalledWith('/workouts/1');
      actionHandler({ notification: { data: {} } });
      expect(gotoMock).toHaveBeenCalledWith('/dashboard');
      // never an absolute / protocol-relative URL from notification data
      gotoMock.mockClear();
      actionHandler({ notification: { data: { url: 'https://evil.example/x' } } });
      actionHandler({ notification: { data: { url: '//evil.example/x' } } });
      expect(gotoMock.mock.calls.every((c) => c[0] === '/dashboard')).toBe(true);
    })();
  });

  it('swallows a thrown error from checkPermissions', async () => {
    checkPermissionsMock.mockRejectedValue(new Error('native failure'));
    await expect(initPushNotifications()).resolves.toBe('failed');
  });
});

describe('initPushNotifications (web)', () => {
  beforeEach(() => isNativePlatformMock.mockReturnValue(false));

  it('does nothing in an iPhone browser tab (web push needs the Home Screen app there)', async () => {
    isStandaloneMock.mockReturnValue(false);
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)');
    const ready = vi.fn();
    vi.stubGlobal('PushManager', function PushManager() {});
    Object.defineProperty(navigator, 'serviceWorker', { get: ready, configurable: true });
    await initPushNotifications();
    expect(ready).not.toHaveBeenCalled();
    expect(apiPostMock).not.toHaveBeenCalled();
    // @ts-expect-error test cleanup
    delete navigator.serviceWorker;
  });

  describe('in a desktop / Android browser tab', () => {
    const KEY = 'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U';
    let subscribe: ReturnType<typeof vi.fn>;
    let getSubscription: ReturnType<typeof vi.fn>;
    let register: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      isStandaloneMock.mockReturnValue(false);
      vi.stubEnv('VITE_VAPID_PUBLIC_KEY', KEY);
      vi.stubGlobal('PushManager', function PushManager() {});
      subscribe = vi.fn().mockResolvedValue({ toJSON: () => ({ endpoint: 'https://push.example/1' }) });
      getSubscription = vi.fn().mockResolvedValue(null);
      const reg = { pushManager: { subscribe, getSubscription } };
      register = vi.fn().mockResolvedValue(reg);
      Object.defineProperty(navigator, 'serviceWorker', {
        value: { ready: Promise.resolve(reg), getRegistration: () => Promise.resolve(reg), register },
        configurable: true
      });
    });

    afterEach(() => {
      vi.unstubAllEnvs();
      // @ts-expect-error test cleanup
      delete navigator.serviceWorker;
    });

    it('subscribes and registers the token once permission is granted', async () => {
      vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
      await expect(initPushNotifications()).resolves.toBe('ok');
      // Nothing else registers the push worker, so setup does.
      expect(register).toHaveBeenCalledWith('/service-worker.js', expect.objectContaining({ scope: '/' }));
      expect(subscribe).toHaveBeenCalled();
      expect(apiPostMock).toHaveBeenCalledWith('/v1/notifications/token', {
        token: JSON.stringify({ endpoint: 'https://push.example/1' }),
        platform: 'web'
      });
    });

    it('never prompts on its own (only the settings button asks)', async () => {
      const requestPermission = vi.fn();
      vi.stubGlobal('Notification', { permission: 'default', requestPermission });
      await expect(initPushNotifications()).resolves.toBe('skipped');
      expect(requestPermission).not.toHaveBeenCalled();
      expect(register).not.toHaveBeenCalled();
      expect(subscribe).not.toHaveBeenCalled();
    });

    it('says when the worker never becomes usable', async () => {
      vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
      register.mockRejectedValue(new Error('SecurityError'));
      await expect(initPushNotifications()).resolves.toBe('no-service-worker');
      expect(subscribe).not.toHaveBeenCalled();
    });

    it('says when this build has no push key', async () => {
      vi.stubEnv('VITE_VAPID_PUBLIC_KEY', '');
      vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
      await expect(initPushNotifications()).resolves.toBe('not-configured');
    });

    it('reports whether a subscription exists', async () => {
      expect(await hasWebPushSubscription()).toBe(false);
      getSubscription.mockResolvedValue({ endpoint: 'x' });
      expect(await hasWebPushSubscription()).toBe(true);
    });
  });

  it('does nothing when serviceWorker/PushManager are unsupported', async () => {
    isStandaloneMock.mockReturnValue(true);
    await initPushNotifications();
    expect(apiPostMock).not.toHaveBeenCalled();
  });

  it('does nothing when VITE_VAPID_PUBLIC_KEY is unset', async () => {
    isStandaloneMock.mockReturnValue(true);
    vi.stubGlobal('PushManager', function PushManager() {});
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { ready: Promise.resolve({ pushManager: {} }) },
      configurable: true
    });
    await initPushNotifications();
    expect(apiPostMock).not.toHaveBeenCalled();
    // @ts-expect-error test cleanup
    delete navigator.serviceWorker;
  });
});
