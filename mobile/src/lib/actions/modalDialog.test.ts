// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { modalDialog } from './modalDialog';

function makeDialog() {
  const node = document.createElement('div');
  node.innerHTML = '<button id="a">A</button><input id="b" /><button id="c">C</button>';
  document.body.appendChild(node);
  return node;
}

const flush = () => new Promise<void>((r) => queueMicrotask(() => r()));

function press(key: string, shiftKey = false) {
  const ev = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true });
  document.dispatchEvent(ev);
  return ev;
}

afterEach(() => {
  document.body.innerHTML = '';
  document.body.style.overflow = '';
});

describe('modalDialog', () => {
  it('focuses the first control, traps Tab, and restores focus and scroll on destroy', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const node = makeDialog();
    const action = modalDialog(node);
    await flush();
    expect(document.activeElement?.id).toBe('a');
    expect(document.body.style.overflow).toBe('hidden');

    (node.querySelector('#c') as HTMLElement).focus();
    expect(press('Tab').defaultPrevented).toBe(true);
    expect(document.activeElement?.id).toBe('a');

    expect(press('Tab', true).defaultPrevented).toBe(true);
    expect(document.activeElement?.id).toBe('c');

    action.destroy();
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe('');
  });

  it('calls onEscape only for the top-most dialog', async () => {
    const outerClose = vi.fn();
    const innerClose = vi.fn();
    const outer = modalDialog(makeDialog(), { onEscape: outerClose });
    const inner = modalDialog(makeDialog(), { onEscape: innerClose });
    await flush();
    press('Escape');
    expect(innerClose).toHaveBeenCalledTimes(1);
    expect(outerClose).not.toHaveBeenCalled();

    inner.destroy();
    press('Escape');
    expect(outerClose).toHaveBeenCalledTimes(1);
    outer.destroy();
    expect(document.body.style.overflow).toBe('');
  });
});
