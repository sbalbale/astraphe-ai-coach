/**
 * Primary navigation model (Graphite + Sky overhaul).
 *
 * Five tabs; each owns a group of routes. Profile ("Me") is reached from the
 * avatar in the header rather than a tab.
 */

export type NavTab = { id: string; label: string; title: string; routes: string[] };

export const NAV_TABS: NavTab[] = [
  { id: '/dashboard', label: 'Today', title: 'Today', routes: ['/', '/dashboard'] },
  { id: '/training', label: 'Training', title: 'Training', routes: ['/training', '/zones'] },
  { id: '/recovery', label: 'Body', title: 'Body', routes: ['/recovery', '/sleep', '/strain'] },
  { id: '/plan', label: 'Plan', title: 'Plan', routes: ['/plan'] },
  { id: '/chat', label: 'Coach', title: 'Coach', routes: ['/chat'] }
];

/** Sub-tabs shown under the header for tabs that group several routes. */
export const SUBTABS: Record<string, { id: string; label: string }[]> = {
  '/training': [
    { id: '/training', label: 'Log' },
    { id: '/zones', label: 'Zones' }
  ],
  '/recovery': [
    { id: '/recovery', label: 'Recovery' },
    { id: '/sleep', label: 'Sleep' },
    { id: '/strain', label: 'Strain' }
  ]
};

/** Tab id that owns `path`, or null for routes outside the tab bar (e.g. /profile). */
export function activeTabFor(path: string): string | null {
  const tab = NAV_TABS.find((t) => t.routes.includes(path));
  return tab ? tab.id : null;
}

/** Header title for `path`. */
export function titleFor(path: string): string {
  if (path.startsWith('/profile')) return 'Me';
  const tab = NAV_TABS.find((t) => t.routes.includes(path));
  return tab ? tab.title : '';
}

/** Sub-tabs for the tab that owns `path`, if any. */
export function subtabsFor(path: string): { id: string; label: string }[] | null {
  const tab = activeTabFor(path);
  return tab ? SUBTABS[tab] ?? null : null;
}
