/**
 * Per-page content for the mobile header that lives in `+layout.svelte`:
 * the mono eyebrow above the title and the controls on its right (day
 * arrows, add button). A page sets what it needs in an `$effect` and
 * returns `reset` as the cleanup so the next page starts blank.
 */
export const pageHeader = $state<{
  /** Replaces the route's title when set (e.g. "Welcome, Sean" on a new account). */
  title: string;
  eyebrow: string;
  prev: (() => void) | null;
  next: (() => void) | null;
  canNext: boolean;
  add: (() => void) | null;
  addLabel: string;
  today: (() => void) | null;
  dateValue: string;
  dateMax: string;
  dateLabel: string;
  dateMarks: string[];
  segments: { value: string; label: string }[];
  segment: string;
  onSegment: ((value: string) => void) | null;
  /** Outlined icon buttons on the right of the title (e.g. Coach history / new chat). */
  actions: { key: string; label: string; icon: 'history' | 'plus'; onclick: () => void }[];
  /** Wide layouts (tablet / desktop): title and eyebrow when they differ from the phone's. */
  wideTitle: string;
  wideEyebrow: string;
  /** Wide layouts: the page draws its own header (e.g. Training log, Coach). */
  hideOnWide: boolean;
}>({ wideTitle: '', wideEyebrow: '', hideOnWide: false, title: '', eyebrow: '', prev: null, next: null, canNext: true, add: null, addLabel: '', today: null, dateValue: '', dateMax: '', dateLabel: '', dateMarks: [], segments: [], segment: '', onSegment: null, actions: [] });

export function resetPageHeader() {
  pageHeader.title = '';
  pageHeader.eyebrow = '';
  pageHeader.prev = null;
  pageHeader.next = null;
  pageHeader.canNext = true;
  pageHeader.add = null;
  pageHeader.addLabel = '';
  pageHeader.today = null;
  pageHeader.dateValue = '';
  pageHeader.dateMax = '';
  pageHeader.dateLabel = '';
  pageHeader.dateMarks = [];
  pageHeader.segments = [];
  pageHeader.segment = '';
  pageHeader.onSegment = null;
  pageHeader.actions = [];
  pageHeader.wideTitle = '';
  pageHeader.wideEyebrow = '';
  pageHeader.hideOnWide = false;
}
