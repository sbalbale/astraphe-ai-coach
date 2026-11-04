import { describe, expect, it } from 'vitest';
import type { PlanCandidate } from '$lib/types/linking';
import {
  comparisonRows,
  filterSessions,
  hm,
  pendingFor,
  pickerTag,
  plannedBlocks,
  secondsAtOrAbove,
  sessionMeta,
  traceLine,
  unlinkConfirmText,
  unlinkedText
} from './workoutLinking';

const cand = (o: Partial<PlanCandidate> = {}): PlanCandidate => ({
  id: 'p1',
  date: '2026-11-03',
  title: 'Threshold 2×20',
  sport: 'bike',
  duration_minutes: 90,
  projected_tss: 105,
  status: 'planned',
  completed: false,
  link_source: null,
  fit: { day_offset: 0, sport_ok: true, duration_ratio: 1, duration_ok: true, auto_ok: true, score: 0, reason: 'same day · similar duration' },
  linked_here: false,
  has_other_workout: false,
  dismissed: false,
  ...o
});

describe('labels', () => {
  it('formats durations and session meta', () => {
    expect(hm(45)).toBe('45′');
    expect(hm(60)).toBe('1h');
    expect(hm(85)).toBe('1h 25');
    expect(sessionMeta({ date: '2026-11-03', duration_minutes: 90, projected_tss: 105 })).toBe('Tue 3 Nov · 1h 30 · 105 TSS');
  });

  it('explains unlinked and unlink states', () => {
    expect(unlinkedText(true)).toMatch(/isn’t linked/);
    expect(unlinkedText(false)).toMatch(/wasn’t in the plan/);
    expect(unlinkConfirmText({ title: 'VO2 5×4', date: '2026-11-05' }, 'auto')).toBe(
      'VO2 5×4 on Thu 5 Nov goes back to not done. It won’t be auto-matched again.'
    );
    expect(unlinkConfirmText({ title: 'VO2 5×4', date: '2026-11-05' }, 'manual')).not.toMatch(/auto-matched/);
  });
});

describe('comparisonRows', () => {
  it('compares duration and TSS, colouring by how close', () => {
    const rows = comparisonRows({ duration_minutes: 90, projected_tss: 100 }, { duration_seconds: 88 * 60, tss: 130 });
    expect(rows).toEqual([
      { k: 'Duration', p: '1h 30', a: '1h 28', tone: 'good' },
      { k: 'TSS', p: '100', a: '130 · 130%', tone: 'warn' }
    ]);
  });

  it('adds time at threshold only with power targets, a power stream and FTP', () => {
    const structure = [{ name: 'Block', duration_minutes: 2, target_power_percent_ftp: 95 }];
    const watts = [300, 300, 300, 100];
    const rows = comparisonRows({ duration_minutes: 2, projected_tss: 0, structure }, { duration_seconds: 120, tss: null }, { watts, step: 40, ftp: 300 });
    expect(rows.at(-1)).toEqual({ k: 'Time at threshold', p: '2′', a: '2′', tone: 'good' });
    expect(comparisonRows({ duration_minutes: 2, projected_tss: 0, structure }, { duration_seconds: 120, tss: null })).toHaveLength(1);
  });

  it('counts seconds above a threshold with real time gaps (capped)', () => {
    expect(secondsAtOrAbove([5, 1, 5, 5], 4, [0, 10, 20, 100])).toBe(10 + 30 + 1);
  });
});

describe('chart geometry', () => {
  it('lays planned blocks along the span with zone colours', () => {
    const b = plannedBlocks(
      [
        { name: 'Warm-up', duration_minutes: 15, target_power_percent_ftp: 60 },
        { name: 'Block', duration_minutes: 15, target_power_percent_ftp: 95 }
      ],
      30,
      300,
      100
    );
    expect(b.map((x) => Math.round(x.x))).toEqual([0, 150]);
    expect(b[0].color).toBe('var(--zone-2)');
    expect(b[1].color).toBe('var(--zone-4)');
    expect(b[1].h).toBeGreaterThan(b[0].h);
  });

  it('downsamples a stream into a polyline', () => {
    const pts = traceLine([100, 200, 300, 400], undefined, 60, 4, 400, 100, 400, 2).split(' ');
    expect(pts).toHaveLength(2);
    expect(traceLine(undefined, undefined, 1, 10, 100, 100, 100)).toBe('');
  });
});

describe('picker', () => {
  it('tags rows', () => {
    expect(pickerTag(cand({ linked_here: true }))?.label).toBe('LINKED HERE');
    expect(pickerTag(cand({ completed: true }))?.label).toBe('DONE · NO FILE');
    expect(pickerTag(cand({ fit: { ...cand().fit, sport_ok: false } }))?.label).toBe('DIFFERENT SPORT');
    expect(pickerTag(cand())).toBeNull();
  });

  it('asks before replacing a link or crossing sports', () => {
    expect(pendingFor(cand(), 'bike')).toBeNull();
    expect(pendingFor(cand({ has_other_workout: true }), 'bike')).toMatchObject({ kicker: 'REPLACE LINK', cta: 'Replace' });
    const p = pendingFor(cand({ fit: { ...cand().fit, sport_ok: false } }), 'row');
    expect(p).toMatchObject({ kicker: 'DIFFERENT SPORT', cta: 'Link anyway' });
    expect(p?.text).toBe('Planned bike, recorded row. Linking still marks the session done.');
  });

  it('filters by title or date', () => {
    const rows = [cand(), cand({ id: 'p2', title: 'Easy spin', date: '2026-11-04' })];
    expect(filterSessions(rows, 'easy').map((r) => r.id)).toEqual(['p2']);
    expect(filterSessions(rows, 'tue').map((r) => r.id)).toEqual(['p1']);
    expect(filterSessions(rows, '')).toHaveLength(2);
  });
});
