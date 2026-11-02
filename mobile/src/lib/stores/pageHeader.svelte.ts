/**
 * Per-page content for the mobile header that lives in `+layout.svelte`:
 * the mono eyebrow above the title and the controls on its right (day
 * arrows, add button). A page sets what it needs in an `$effect` and
 * returns `reset` as the cleanup so the next page starts blank.
 */
export const pageHeader = $state<{
  eyebrow: string;
  prev: (() => void) | null;
  next: (() => void) | null;
  canNext: boolean;
  add: (() => void) | null;
  addLabel: string;
}>({ eyebrow: '', prev: null, next: null, canNext: true, add: null, addLabel: '' });

export function resetPageHeader() {
  pageHeader.eyebrow = '';
  pageHeader.prev = null;
  pageHeader.next = null;
  pageHeader.canNext = true;
  pageHeader.add = null;
  pageHeader.addLabel = '';
}
