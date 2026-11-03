/**
 * Viewport size, shared by the layout and pages that change layout on tablets / desktop.
 *
 * - `wide` (≥ 768 px): sidebar navigation instead of the bottom tab bar; pages may use
 *   multi-column layouts.
 * - `landscape` (≥ 1200 px): room for the expanded sidebar and three-column layouts
 *   (iPad landscape / desktop). Narrower wide screens (iPad portrait) get the collapsed rail.
 *
 * `+layout.svelte` writes `width`; everything else only reads.
 */
const RAIL_KEY = 'astraphe.navCollapsed';

function readRailPref(): boolean | null {
  try {
    const v = typeof localStorage !== 'undefined' ? localStorage.getItem(RAIL_KEY) : null;
    return v === '1' ? true : v === '0' ? false : null;
  } catch {
    return null;
  }
}

class ViewportState {
  width = $state(0);
  /** The user's explicit sidebar choice; null follows the screen width. */
  railPref = $state<boolean | null>(readRailPref());

  get wide(): boolean {
    return this.width >= 768;
  }

  get landscape(): boolean {
    return this.width >= 1200;
  }

  /** Sidebar shown as the 76 px icon rail. */
  get railCollapsed(): boolean {
    return this.railPref ?? !this.landscape;
  }

  toggleRail(): void {
    this.railPref = !this.railCollapsed;
    try {
      localStorage.setItem(RAIL_KEY, this.railPref ? '1' : '0');
    } catch {
      /* private mode */
    }
  }
}

export const viewport = new ViewportState();
