import { describe, expect, it } from 'vitest';
import {
  baselineBefore,
  bodyEyebrow,
  dayStrain,
  hourTicks,
  nightWindowLabel,
  recoveryWhy,
  seriesWindow,
  sourcesLabel,
  sparkline,
  workoutMeta
} from './bodyWide';

describe('nightWindowLabel / sourcesLabel / bodyEyebrow', () => {
  it('labels the night ending on the wake day', () => {
    expect(nightWindowLabel('2026-11-02')).toBe('SUN → MON 2 NOV');
  });

  it('lists devices once, skipping Astraphe-computed scores', () => {
    const row = { metric_sources: { hrv_rmssd: 'whoop', sleep_duration_min: 'garmin', recovery_score: 'astraphe', resting_hr: 'whoop' }, hrv_source: 'whoop' };
    expect(sourcesLabel(row)).toBe('WHOOP + GARMIN');
    expect(sourcesLabel(null)).toBe('');
  });

  it('joins window and sources, dropping empty parts', () => {
    expect(bodyEyebrow('2026-11-02', { hrv_source: 'garmin' })).toBe('SUN → MON 2 NOV · GARMIN');
    expect(bodyEyebrow('2026-11-02', {})).toBe('SUN → MON 2 NOV');
  });
});

describe('sparkline', () => {
  it('needs two values', () => {
    expect(sparkline([null, 5, null])).toBeNull();
  });

  it('skips gaps and keeps points inside the box', () => {
    const s = sparkline([50, null, 60, 55])!;
    const pts = s.points.split(' ').map((p) => p.split(',').map(Number));
    expect(pts).toHaveLength(3);
    for (const [x, y] of pts) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(200);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(40);
    }
    expect(s.bandH).toBeGreaterThan(0);
  });

  it('handles a flat series', () => {
    expect(sparkline([4, 4, 4])).not.toBeNull();
  });
});

const series = [
  { date: '2026-10-27', hrv_rmssd: 50, resting_hr: 50 },
  { date: '2026-10-28', hrv_rmssd: 50, resting_hr: 50 },
  { date: '2026-10-29', hrv_rmssd: 50, resting_hr: 52 },
  { date: '2026-11-02', hrv_rmssd: 55, resting_hr: 48, sleep_duration_min: 462 }
];

describe('baselines', () => {
  it('averages the days before, excluding the day itself', () => {
    expect(baselineBefore(series, '2026-11-02', 'hrv_rmssd')).toBe(50);
    expect(baselineBefore(series, '2026-10-27', 'hrv_rmssd')).toBeNull();
  });

  it('windows a field oldest first with nulls for gaps', () => {
    const w = seriesWindow(series, '2026-11-02', 'hrv_rmssd', 7);
    expect(w).toEqual([50, 50, 50, null, null, null, 55]);
  });

  it('explains a day from its own numbers', () => {
    expect(recoveryWhy(series, '2026-11-02')).toBe('HRV 10% above your 7-day baseline, resting HR 3 bpm lower, 7h 42m asleep.');
    expect(recoveryWhy(series, '2026-11-01')).toBeNull();
  });
});

describe('dayStrain', () => {
  it('uses workouts when they exceed the wearable score', () => {
    const r = dayStrain({ strain_score: 20 }, [{ strain_score: 40 }, { tss: 75 }]);
    expect(r.score).toBe(90);
    expect(r.workouts.map((p) => p.value)).toEqual([40, 50]);
    expect(r.activity).toBe(0);
  });

  it('attributes wearable strain beyond workouts to daily activity', () => {
    const r = dayStrain({ strain_score: 64 }, [{ strain_score: 58 }]);
    expect(r.score).toBe(64);
    expect(r.activity).toBe(6);
  });

  it('uses the wearable score alone on a rest day', () => {
    expect(dayStrain({ strain_score: 12.4 }, []).score).toBe(12);
    expect(dayStrain(null, []).score).toBe(0);
  });
});

describe('workoutMeta / hourTicks', () => {
  it('formats duration, HR and TSS when present', () => {
    expect(workoutMeta({ duration_seconds: 5100, avg_hr: 148, tss: 92 })).toBe('1h 25m · 148 bpm avg · 92 TSS');
    expect(workoutMeta({ duration_seconds: 2520 })).toBe('42m');
  });

  it('places round even hours across the night', () => {
    const start = new Date(2026, 10, 1, 22, 51).getTime();
    const end = new Date(2026, 10, 2, 7, 12).getTime();
    const ticks = hourTicks(start, end);
    expect(ticks.map((t) => t.label)).toEqual(['00:00', '02:00', '04:00', '06:00']);
    expect(ticks[0].pct).toBeGreaterThan(0);
    expect(ticks[ticks.length - 1].pct).toBeLessThan(100);
  });
});
