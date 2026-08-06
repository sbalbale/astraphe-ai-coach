import { get } from 'svelte/store';
import { describe, expect, it } from 'vitest';
import { closeConfirm, confirm, confirmState } from './confirm';

describe('confirm / closeConfirm', () => {
  it('opens the confirm state with defaults applied', () => {
    const promise = confirm({ title: 'Delete?', message: 'Are you sure?' });
    const state = get(confirmState);
    expect(state?.open).toBe(true);
    expect(state?.title).toBe('Delete?');
    expect(state?.confirmText).toBe('Confirm');
    expect(state?.cancelText).toBe('Cancel');
    expect(state?.confirmTone).toBe('primary');
    closeConfirm(true);
    return promise.then((result) => {
      expect(result).toBe(true);
    });
  });

  it('applies custom options over defaults', () => {
    const promise = confirm({
      title: 'Danger',
      message: 'Really?',
      confirmText: 'Yes, delete',
      cancelText: 'No',
      confirmTone: 'danger'
    });
    const state = get(confirmState);
    expect(state?.confirmText).toBe('Yes, delete');
    expect(state?.confirmTone).toBe('danger');
    closeConfirm(false);
    return promise.then((result) => {
      expect(result).toBe(false);
    });
  });

  it('closeConfirm resolves false and clears state', async () => {
    const promise = confirm({ title: 't', message: 'm' });
    closeConfirm(false);
    const result = await promise;
    expect(result).toBe(false);
    expect(get(confirmState)).toBeNull();
  });

  it('closeConfirm on already-null state is a no-op', () => {
    closeConfirm(true); // state already null from previous test / no confirm() pending
    expect(get(confirmState)).toBeNull();
  });

});
