import { writable } from 'svelte/store';

export type ConfirmTone = 'danger' | 'primary';

export type ConfirmOptions = {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  confirmTone?: ConfirmTone;
};

type ConfirmInternalState = ConfirmOptions & {
  open: boolean;
  resolve: (v: boolean) => void;
};

export const confirmState = writable<ConfirmInternalState | null>(null);

export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    confirmState.set({
      open: true,
      title: options.title,
      message: options.message,
      confirmText: options.confirmText ?? 'Confirm',
      cancelText: options.cancelText ?? 'Cancel',
      confirmTone: options.confirmTone ?? 'primary',
      resolve
    });
  });
}

export function closeConfirm(result: boolean) {
  confirmState.update((s) => {
    if (!s) return null;
    try {
      s.resolve(result);
    } catch {
      // ignore
    }
    return null;
  });
}

