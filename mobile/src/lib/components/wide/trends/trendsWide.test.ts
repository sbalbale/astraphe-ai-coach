import { describe, expect, it } from 'vitest';
import {
  averageCompletedTss,
  percentages,
  rampRatePerWeek,
  rangeStart,
  splitInsight,
  sportsLabel,
  weeklyBuckets,
  zoneSecondsInWindow,
  zoneWindow
} from './trendsWide';

// Wednesday 4 Nov 2026
const TODAY = new Date(2026, 10, 4, 12);

describe('weeklyBuckets', () => {
  it('buckets Monday-start weeks, keeps end-of-week load', () => {
    const rows = [
      { date: '2026-10-19', daily_tss: 100, ctl: 50, atl: 55 },
      { date: '2026-10-25', daily_tss: 300, ctl: 52, atl: 60 },
      { date: '2026-10-26', daily_tss: 200, ctl: 51, atl: 50 },
      { date: '2026-11-03', daily_tss: 80, ctl: 50, atl: 48 }
    ];
    const planned = [{ date: '2026-11-06', projected_tss: 120 }];
    const b = weeklyBuckets(rows, planned, 3, TODAY);
    expect(b.map((w) => w.tss)).toEqual([400, 200, 80]);
    expect(b[0].ctl).toBe(52);
    expect(b[2].current).toBe(true);
    expect(b[2].planned).toBe(120);
    expect(rangeStart(TODAY, 3).getDate()).toBe(19);
  });

  it('averages only completed weeks with load', () => {
    const b = weeklyBuckets([{ date: '2026-10-26', daily_tss: 300 }, { date: '2026-11-02', daily_tss: 50 }], [], 3, TODAY);
    expect(averageCompletedTss(b)).toBe(300);
  });
});

describe('rampRatePerWeek', () => {
  it('is fitness change per week over ~28 days', () => {
    const rows = [
      { date: '2026-10-07', ctl: 50 },
      { date: '2026-10-20', ctl: 54 },
      { date: '2026-11-04', ctl: 58 }
    ];
    expect(rampRatePerWeek(rows)).toBe(2);
  });
  it('needs at least three weeks of history', () => {
    expect(rampRatePerWeek([{ date: '2026-10-30', ctl: 50 }, { date: '2026-11-04', ctl: 52 }])).toBeNull();
  });
});

describe('zones', () => {
  it('windows weeks and months relative to today', () => {
    expect(zoneWindow('week', 0, TODAY).start.getDate()).toBe(2);
    expect(zoneWindow('week', -1, TODAY).start.getDate()).toBe(26);
    expect(zoneWindow('month', -1, TODAY).start.getMonth()).toBe(9);
  });

  it('sums zone time for workouts inside the window', () => {
    const { start, end } = zoneWindow('week', 0, TODAY);
    const w = [
      { started_at: '2026-11-03T08:00:00', duration_seconds: 3600, hr_zone_1_pct: 50, hr_zone_2_pct: 50, hr_zone_3_pct: 0, hr_zone_4_pct: 0, hr_zone_5_pct: 0 },
      { started_at: '2026-10-20T08:00:00', duration_seconds: 3600, hr_zone_1_pct: 100 },
      { started_at: '2026-11-03T18:00:00', duration_seconds: 3600, hr_zone_1_pct: null }
    ];
    expect(zoneSecondsInWindow(w, start, end)).toEqual([1800, 1800, 0, 0, 0]);
  });

  it('rounds percentages to exactly 100', () => {
    expect(percentages([1, 1, 1]).reduce((a, b) => a + b, 0)).toBe(100);
    expect(percentages([0, 0])).toEqual([0, 0]);
  });

  it('describes the split', () => {
    expect(splitInsight([40, 40, 10, 8, 2], 3600)).toContain('80% easy');
    expect(splitInsight([0, 0, 0, 0, 0], 0)).toContain('No heart-rate');
  });

  it('labels the sports trained', () => {
    const w = [
      { started_at: '2026-11-01T08:00:00', sport: 'Ride' },
      { started_at: '2026-11-02T08:00:00', sport: 'cycling' },
      { started_at: '2026-11-03T08:00:00', sport: 'Run' },
      { started_at: '2025-01-01T08:00:00', sport: 'Swim' }
    ];
    expect(sportsLabel(w, new Date(2026, 9, 1))).toBe('BIKE + RUN');
  });
});
