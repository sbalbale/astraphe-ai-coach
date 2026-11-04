import { describe, expect, it } from 'vitest';
import { NOTIFICATION_DEFAULTS } from '$lib/notificationSettings';
import {
  deviceLabel,
  devicesLine,
  groupedTypes,
  isIosUserAgent,
  permissionState,
  quietNote,
  testResultMessage,
  toggleChannel
} from './notificationUi';

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1';
const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15';

describe('permissionState', () => {
  const web = { native: false, ios: false, standalone: false };
  it('asks iPhone browsers to install first', () => {
    expect(permissionState({ ...web, ios: true, webPermission: null })).toBe('install');
    expect(permissionState({ ...web, ios: true, standalone: true, webPermission: 'default' })).toBe('default');
  });
  it('maps browser permission', () => {
    expect(permissionState({ ...web, webPermission: 'granted' })).toBe('granted');
    expect(permissionState({ ...web, webPermission: 'denied' })).toBe('denied');
    expect(permissionState({ ...web, webPermission: 'default' })).toBe('default');
    expect(permissionState({ ...web, webPermission: null })).toBe('unsupported');
  });
  it('maps native permission', () => {
    expect(permissionState({ ...web, native: true, nativeStatus: 'granted', webPermission: null })).toBe('granted');
    expect(permissionState({ ...web, native: true, nativeStatus: 'prompt', webPermission: null })).toBe('default');
  });
});

describe('devices', () => {
  it('detects iOS including iPadOS desktop mode', () => {
    expect(isIosUserAgent(IPHONE)).toBe(true);
    expect(isIosUserAgent(MAC, 5)).toBe(true);
    expect(isIosUserAgent(MAC, 0)).toBe(false);
  });
  it('labels the device', () => {
    expect(deviceLabel(IPHONE)).toBe('this iPhone');
    expect(deviceLabel(MAC, 5)).toBe('this iPad');
    expect(deviceLabel(MAC)).toBe('this browser');
  });
  it('describes the device count', () => {
    expect(devicesLine(2)).toMatch(/2 devices/);
    expect(devicesLine(1)).toMatch(/only device/);
  });
});

describe('channels', () => {
  it('keeps at least one channel on', () => {
    expect(toggleChannel(NOTIFICATION_DEFAULTS, 'debrief', 'push')).toBeNull();
    const withEmail = toggleChannel(NOTIFICATION_DEFAULTS, 'weekly', 'email')!;
    expect(withEmail.types.weekly.email).toBe(true);
    expect(toggleChannel(withEmail, 'weekly', 'push')!.types.weekly).toMatchObject({ push: false, email: true });
  });
  it('refuses email on types that cannot email', () => {
    expect(toggleChannel(NOTIFICATION_DEFAULTS, 'ready', 'email')).toBeNull();
  });
});

describe('copy', () => {
  it('groups types in screen order', () => {
    expect(groupedTypes().map((g) => g.name)).toEqual(['COACH', 'DAILY', 'SUMMARIES', 'ACCOUNT']);
  });
  it('explains quiet hours', () => {
    expect(quietNote(NOTIFICATION_DEFAULTS)).toMatch(/between 22:00 and 07:00/);
    expect(quietNote({ ...NOTIFICATION_DEFAULTS, quiet: { on: false, from: '22:00', to: '07:00' } })).toMatch(/any time/);
  });
  it('explains test results', () => {
    expect(testResultMessage('sent', 'this iPhone')!.ok).toBe(true);
    expect(testResultMessage('rate_limited', 'this iPhone')!.text).toMatch(/just sent/);
    expect(testResultMessage(null, 'x')).toBeNull();
  });
});
