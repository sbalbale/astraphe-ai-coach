import { describe, expect, it } from 'vitest';
import { NAV_TABS } from './navTabs';
import { PALETTE_PAGES, WIDE_NAV, filterPalette, groupPalette } from './wideNav';

describe('WIDE_NAV', () => {
  it('mirrors the five tabs with 1–5 shortcuts', () => {
    expect(WIDE_NAV.map((n) => n.id)).toEqual(NAV_TABS.map((t) => t.id));
    expect(WIDE_NAV.map((n) => n.key)).toEqual(['1', '2', '3', '4', '5']);
  });

  it('only links sub-views to routes the tab owns', () => {
    for (const item of WIDE_NAV) {
      const owned = NAV_TABS.find((t) => t.id === item.id)!.routes;
      for (const s of item.subs) for (const r of s.routes) expect(owned).toContain(r);
    }
  });
});

describe('filterPalette', () => {
  it('returns everything for an empty query', () => {
    expect(filterPalette(PALETTE_PAGES, '  ')).toHaveLength(PALETTE_PAGES.length);
  });

  it('matches label or hint, case-insensitively', () => {
    expect(filterPalette(PALETTE_PAGES, 'SLEEP').map((r) => r.href)).toEqual(['/recovery', '/heart-rate']);
    expect(filterPalette(PALETTE_PAGES, 'ftp').map((r) => r.href)).toContain('/profile/training-settings');
  });
});

describe('groupPalette', () => {
  it('keeps first-seen group order', () => {
    const groups = groupPalette(PALETTE_PAGES);
    expect(groups.map((g) => g.name)).toEqual(['GO TO', 'SETTINGS']);
    expect(groups[0].rows[0].label).toBe('Today');
  });
});
