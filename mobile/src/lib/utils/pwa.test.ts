import { afterEach, describe, expect, it, vi } from 'vitest';
import { externalLinkTargetAttr, isStandaloneDisplayMode } from './pwa';

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isStandaloneDisplayMode', () => {
  it('true when display-mode media query matches', () => {
    stubMatchMedia(true);
    expect(isStandaloneDisplayMode()).toBe(true);
  });

  it('false when neither media query nor legacy iOS flag match', () => {
    stubMatchMedia(false);
    expect(isStandaloneDisplayMode()).toBe(false);
  });

  it('true via legacy iOS navigator.standalone flag', () => {
    stubMatchMedia(false);
    Object.defineProperty(window.navigator, 'standalone', { value: true, configurable: true });
    expect(isStandaloneDisplayMode()).toBe(true);
    // @ts-expect-error cleanup test-only property
    delete window.navigator.standalone;
  });
});

describe('externalLinkTargetAttr', () => {
  it('empty string when standalone', () => {
    stubMatchMedia(true);
    expect(externalLinkTargetAttr()).toBe('');
  });

  it('target=_blank when not standalone', () => {
    stubMatchMedia(false);
    expect(externalLinkTargetAttr()).toBe(' target="_blank"');
  });
});
