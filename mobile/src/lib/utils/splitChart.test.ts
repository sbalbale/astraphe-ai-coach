import { describe, expect, it } from 'vitest';
import { buildSplitChart } from './splitChart';
import type { ActivitySplit } from './lapSplits';

const lap = (n: number, secs: number, watts: number | null, hr: number | null, dist = 1000): ActivitySplit => ({
  split_number: n,
  distance: dist,
  elapsed_time: secs,
  pace_seconds: null,
  average_heartrate: hr,
  average_watts: watts,
  average_cadence: null,
  average_speed: null
});

describe('buildSplitChart', () => {
  it('needs at least two laps with something to plot', () => {
    expect(buildSplitChart([lap(1, 60, 200, 140)], 300, 100)).toBeNull();
    expect(buildSplitChart([lap(1, 60, 0, 140, 0), lap(2, 60, 0, 150, 0)], 300, 100)).toBeNull();
  });

  it('sizes bars by duration and power and draws the HR line', () => {
    const c = buildSplitChart([lap(1, 100, 100, 120), lap(2, 300, 200, 160)], 303, 100, 3)!;
    expect(c.metric).toBe('power');
    expect(c.bars[0].w).toBe(75);
    expect(c.bars[1].w).toBe(225);
    expect(c.bars[1].x).toBe(78);
    // Tallest bar = highest power, sits on the baseline.
    expect(c.bars[1].y + c.bars[1].h).toBe(100);
    expect(c.bars[0].h).toBeLessThan(c.bars[1].h);
    // Higher HR is drawn higher (smaller y).
    expect(c.bars[1].hy!).toBeLessThan(c.bars[0].hy!);
    expect(c.hrLine.split(' ')).toHaveLength(2);
  });

  it('falls back to speed and skips laps without HR in the line', () => {
    const c = buildSplitChart([lap(1, 100, null, null, 500), lap(2, 100, null, 150, 1000)], 200, 80)!;
    expect(c.metric).toBe('speed');
    expect(c.bars[0].hy).toBeNull();
    expect(c.hrLine.split(' ')).toHaveLength(1);
  });
});
