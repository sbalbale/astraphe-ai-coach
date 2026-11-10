import { describe, expect, it } from 'vitest';
import {
  coachLine,
  daysToGoal,
  gridValues,
  ratePerWeek,
  smooth,
  tickOffsets,
  toUnit,
  withOffsets
} from './weightView';
import type { WeighIn } from '$lib/types/weight';
import { addDays, format, parseISO } from 'date-fns';

const wi = (date: string, kg: number, over: Partial<WeighIn> = {}): WeighIn => ({
  id: date + kg,
  date,
  measured_at: `${date}T12:00:00Z`,
  weight_kg: kg,
  body_fat_pct: null,
  source: 'garmin',
  time_known: true,
  ...over
});

describe('withOffsets', () => {
  it('orders by day then time and drops future days', () => {
    const e = withOffsets([wi('2026-11-09', 80), wi('2026-11-01', 81), wi('2026-11-10', 79)], '2026-11-09');
    expect(e.map((x) => x.o)).toEqual([-8, 0]);
  });
});

describe('smooth', () => {
  it('is a plain EWMA for daily readings', () => {
    const t = smooth([{ o: -1, v: 80 }, { o: 0, v: 90 }], -1);
    expect(t.get(-1)).toBe(80);
    expect(t.get(0)).toBeCloseTo(81);
  });

  it('interpolates across a gap and lets a long gap move the trend further', () => {
    const t = smooth([{ o: -60, v: 85 }, { o: 0, v: 83 }], -90);
    expect(t.get(-90)).toBeNull();
    expect(t.get(-30)!).toBeCloseTo(84.0, 1);
    // 60 days: 1 - 0.9^60 ≈ 0.998 of the way
    expect(t.get(0)!).toBeCloseTo(83.0, 1);
  });

  it('averages several readings on one day', () => {
    expect(smooth([{ o: 0, v: 80 }, { o: 0, v: 82 }], 0).get(0)).toBe(81);
  });
});

describe('rate and projection', () => {
  // 35 daily weigh-ins losing 0.05 kg/day (0.35 kg/wk), ending today.
  const entries = withOffsets(
    Array.from({ length: 35 }, (_, i) => wi(format(addDays(parseISO('2026-10-06'), i), 'yyyy-MM-dd'), 84 - i * 0.05)),
    '2026-11-09'
  );

  it('needs two recent weigh-ins', () => {
    const one = withOffsets([wi('2026-11-09', 80)], '2026-11-09');
    expect(ratePerWeek(one, smooth([{ o: 0, v: 80 }], -28))).toBeNull();
  });

  it('measures the 4-week trend change per week', () => {
    const tr = smooth(entries.map((e) => ({ o: e.o, v: e.weight_kg })), -40);
    // Smoothing lags a steady slope (more so a week after the first reading), so it
    // reads a bit under the true -0.35 kg/wk.
    const r = ratePerWeek(entries, tr)!;
    expect(r).toBeLessThan(-0.25);
    expect(r).toBeGreaterThan(-0.4);
  });

  it('projects toward a goal in the direction of travel only', () => {
    expect(daysToGoal(80, 78, -0.5)).toBe(28);
    expect(daysToGoal(80, 78, 0.5)).toBe(0);
    expect(daysToGoal(80, 82, 0.5)).toBe(28);
    expect(daysToGoal(80, null, -0.5)).toBe(0);
    expect(daysToGoal(80, 60, -0.5)).toBe(120);
  });
});

describe('axis and copy', () => {
  it('grid stays at six lines or fewer', () => {
    expect(gridValues(80.2, 84.9, 1)).toEqual([81, 82, 83, 84]);
    expect(gridValues(150, 190, 2).length).toBeLessThanOrEqual(6);
  });

  it('ticks per range', () => {
    expect(tickOffsets(30)).toEqual([0, -7, -14, -21, -28]);
    expect(tickOffsets(365)).toEqual([0, -91, -182, -273, -364]);
  });

  it('converts units', () => {
    expect(toUnit(100, 'lb')).toBeCloseTo(220.46, 2);
  });

  it('coach line reflects the rate', () => {
    expect(coachLine(null, null, 'kg', null)).toMatch(/Weigh in/);
    expect(coachLine(-1, 80, 'kg', null)).toMatch(/more than 1%/);
    expect(coachLine(-0.4, 80, 'kg', 3.5)).toMatch(/Down 0.4 kg a week.*3.50 W\/kg/);
    expect(coachLine(0, 80, 'lb', null)).toMatch(/steady.*lb/);
  });
});

describe('smooth after the last reading', () => {
  it('holds the trend flat until today', () => {
    const t = smooth([{ o: -10, v: 80 }], -20);
    expect(t.get(-5)).toBe(80);
    expect(t.get(0)).toBe(80);
  });
});
