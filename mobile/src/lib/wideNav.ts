/**
 * Wide (tablet / desktop) navigation model: the five sections of `navTabs.ts` with
 * their 1–5 keyboard shortcuts, sidebar icons and Training's sub-views.
 */
export type WideNavItem = {
  id: string;
  label: string;
  href: string;
  key: string;
  icon: string;
  subs: { label: string; href: string; routes: string[] }[];
};

export const WIDE_NAV: WideNavItem[] = [
  {
    id: '/dashboard',
    label: 'Today',
    href: '/dashboard',
    key: '1',
    icon: 'M8 12a4 4 0 1 0 8 0a4 4 0 1 0-8 0M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
    subs: []
  },
  {
    id: '/training',
    label: 'Training',
    href: '/training',
    key: '2',
    icon: 'M3 12h4l3-7 4 14 3-7h4',
    subs: [
      { label: 'Log', href: '/training', routes: ['/training'] },
      { label: 'Trends & zones', href: '/trends', routes: ['/trends', '/zones'] }
    ]
  },
  {
    id: '/recovery',
    label: 'Body',
    href: '/recovery',
    key: '3',
    icon: 'M20.8 8.6a5 5 0 0 0-8.8-3.2 5 5 0 0 0-8.8 3.2c0 5.4 8.8 11 8.8 11s8.8-5.6 8.8-11z',
    subs: []
  },
  {
    id: '/plan',
    label: 'Plan',
    href: '/plan',
    key: '4',
    icon: 'M6 5h12a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V8a3 3 0 0 1 3-3zM3 10h18M8 3v4M16 3v4',
    subs: []
  },
  {
    id: '/chat',
    label: 'Coach',
    href: '/chat',
    key: '5',
    icon: 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z',
    subs: []
  }
];

export type PaletteRow = { group: string; tag: string; label: string; hint: string; href: string; key?: string };

/** Static rows of the ⌘K palette; recent workouts are added at runtime. */
export const PALETTE_PAGES: PaletteRow[] = [
  { group: 'GO TO', tag: 'TOD', label: 'Today', hint: 'Session, readiness, coach note', href: '/dashboard', key: '1' },
  { group: 'GO TO', tag: 'LOG', label: 'Training log', hint: 'Activities, map, charts, laps', href: '/training', key: '2' },
  { group: 'GO TO', tag: 'TRD', label: 'Trends & zones', hint: 'Fitness, fatigue, weekly TSS, zones', href: '/trends' },
  { group: 'GO TO', tag: 'BDY', label: 'Body', hint: 'Recovery, sleep, strain', href: '/recovery', key: '3' },
  { group: 'GO TO', tag: 'PLN', label: 'Plan', hint: 'Month and week calendar', href: '/plan', key: '4' },
  { group: 'GO TO', tag: 'CHT', label: 'Coach', hint: 'Conversations', href: '/chat', key: '5' },
  { group: 'GO TO', tag: 'RDY', label: 'Readiness', hint: 'What goes into today’s score', href: '/readiness' },
  { group: 'SETTINGS', tag: 'ME', label: 'Profile', hint: 'Account and preferences', href: '/profile' },
  { group: 'SETTINGS', tag: 'APP', label: 'Connected apps', hint: 'Garmin, WHOOP, Intervals.icu', href: '/profile/connections' },
  { group: 'SETTINGS', tag: 'FTP', label: 'Training settings', hint: 'FTP, threshold HR, zones', href: '/profile/training-settings' },
  { group: 'SETTINGS', tag: 'INF', label: 'Personal info', hint: 'Name, weight, birthday', href: '/profile/personal-info' }
];

/** Rows matching `query` (all rows when empty), in their original order. */
export function filterPalette(rows: PaletteRow[], query: string): PaletteRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((r) => `${r.label} ${r.hint}`.toLowerCase().includes(q));
}

/** Group rows for display, keeping first-seen group order. */
export function groupPalette(rows: PaletteRow[]): { name: string; rows: PaletteRow[] }[] {
  const out: { name: string; rows: PaletteRow[] }[] = [];
  for (const r of rows) {
    let g = out.find((x) => x.name === r.group);
    if (!g) out.push((g = { name: r.group, rows: [] }));
    g.rows.push(r);
  }
  return out;
}
