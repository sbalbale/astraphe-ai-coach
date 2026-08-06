import { afterEach, describe, expect, it, vi } from 'vitest';

const gotoMock = vi.fn();
vi.mock('$app/navigation', () => ({ goto: (...args: unknown[]) => gotoMock(...args) }));
vi.mock('$app/paths', () => ({ resolve: (p: string) => p }));

import { installInAppLinkInterceptor, navTo } from './nav';

afterEach(() => {
  gotoMock.mockClear();
});

describe('navTo', () => {
  it('calls goto with resolved path and nav options', () => {
    navTo('/dashboard');
    expect(gotoMock).toHaveBeenCalledWith('/dashboard', { keepFocus: true, noScroll: true });
  });
});

describe('installInAppLinkInterceptor', () => {
  function makeAnchorClickEvent(href: string, opts: Partial<MouseEvent> = {}) {
    const anchor = document.createElement('a');
    anchor.setAttribute('href', href);
    document.body.appendChild(anchor);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: opts.button ?? 0 });
    Object.defineProperty(event, 'target', { value: anchor, configurable: true });
    return { anchor, event };
  }

  it('intercepts a same-origin link click and calls goto', () => {
    const uninstall = installInAppLinkInterceptor();
    const { anchor, event } = makeAnchorClickEvent('/settings');
    anchor.dispatchEvent(event);
    expect(gotoMock).toHaveBeenCalled();
    uninstall();
    anchor.remove();
  });

  it('ignores clicks with modifier keys / non-left button', () => {
    const uninstall = installInAppLinkInterceptor();
    const anchor = document.createElement('a');
    anchor.setAttribute('href', '/settings');
    document.body.appendChild(anchor);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 1 });
    anchor.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
    anchor.remove();
  });

  it('ignores anchors with a download attribute', () => {
    const uninstall = installInAppLinkInterceptor();
    const anchor = document.createElement('a');
    anchor.setAttribute('href', '/file.pdf');
    anchor.setAttribute('download', '');
    document.body.appendChild(anchor);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    anchor.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
    anchor.remove();
  });

  it('ignores hash/auth/mailto/tel/javascript links', () => {
    const uninstall = installInAppLinkInterceptor();
    for (const href of ['#section', '/auth/callback', 'mailto:a@b.com', 'tel:12345', 'javascript:void(0)']) {
      const { anchor, event } = makeAnchorClickEvent(href);
      anchor.dispatchEvent(event);
      anchor.remove();
    }
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
  });

  it('ignores cross-origin links', () => {
    const uninstall = installInAppLinkInterceptor();
    const { anchor, event } = makeAnchorClickEvent('https://external.example.com/x');
    anchor.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
    anchor.remove();
  });

  it('ignores clicks with no href attribute (delegated target has none)', () => {
    const uninstall = installInAppLinkInterceptor();
    const anchor = document.createElement('a');
    document.body.appendChild(anchor);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    Object.defineProperty(event, 'target', { value: anchor, configurable: true });
    anchor.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
    anchor.remove();
  });

  it('ignores clicks not on an anchor at all', () => {
    const uninstall = installInAppLinkInterceptor();
    const div = document.createElement('div');
    document.body.appendChild(div);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    div.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    uninstall();
    div.remove();
  });

  it('uninstall removes the listener', () => {
    const uninstall = installInAppLinkInterceptor();
    uninstall();
    const { anchor, event } = makeAnchorClickEvent('/settings');
    anchor.dispatchEvent(event);
    expect(gotoMock).not.toHaveBeenCalled();
    anchor.remove();
  });
});
