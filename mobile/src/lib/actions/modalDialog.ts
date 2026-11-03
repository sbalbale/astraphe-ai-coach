/**
 * Svelte action for modal dialogs and sheets: while the node is mounted it
 * - moves focus into it (first focusable element, else the node itself),
 * - keeps Tab / Shift+Tab inside it,
 * - calls `onEscape` on Escape (only the top-most open dialog reacts),
 * - locks page scroll,
 * and on unmount restores focus to whatever had it before and unlocks scroll.
 */

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type ModalDialogOptions = { onEscape?: () => void };

const stack: HTMLElement[] = [];
let scrollLocks = 0;
let savedOverflow = '';

function lockScroll() {
  if (scrollLocks++ === 0) {
    savedOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
}

function unlockScroll() {
  if (scrollLocks > 0 && --scrollLocks === 0) {
    document.body.style.overflow = savedOverflow;
  }
}

export function focusableWithin(node: HTMLElement): HTMLElement[] {
  return Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute('inert') && el.getAttribute('aria-hidden') !== 'true'
  );
}

export function modalDialog(node: HTMLElement, options: ModalDialogOptions = {}) {
  let opts = options;
  const previouslyFocused = document.activeElement as HTMLElement | null;
  stack.push(node);
  lockScroll();

  if (!node.hasAttribute('tabindex')) node.setAttribute('tabindex', '-1');
  queueMicrotask(() => {
    if (!node.isConnected || node.contains(document.activeElement)) return;
    (focusableWithin(node)[0] ?? node).focus({ preventScroll: true });
  });

  function onKeydown(event: KeyboardEvent) {
    if (stack[stack.length - 1] !== node) return; // a dialog above this one handles it
    if (event.key === 'Escape') {
      if (opts.onEscape) {
        event.preventDefault();
        event.stopPropagation();
        opts.onEscape();
      }
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusableWithin(node);
    if (items.length === 0) {
      event.preventDefault();
      node.focus({ preventScroll: true });
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !node.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !node.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  document.addEventListener('keydown', onKeydown, true);

  return {
    update(next: ModalDialogOptions = {}) {
      opts = next;
    },
    destroy() {
      document.removeEventListener('keydown', onKeydown, true);
      const i = stack.lastIndexOf(node);
      if (i !== -1) stack.splice(i, 1);
      unlockScroll();
      if (previouslyFocused && previouslyFocused.isConnected && typeof previouslyFocused.focus === 'function') {
        previouslyFocused.focus({ preventScroll: true });
      }
    }
  };
}
