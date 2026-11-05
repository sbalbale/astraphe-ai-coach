import { describe, expect, it } from 'vitest';
import {
  blockStats,
  rollingMean,
  hrOnPowerScale,
  inTargetPct,
  mins,
  pvaBlocks,
  targetWindow,
  tracePoints,
  yRange,
  zoneBands
} from './planVsActual';

const ZONES = [
  { zone: 1, min_bpm: 0, max_bpm: 136 },
  { zone: 2, min_bpm: 136, max_bpm: 149 },
  { zone: 3, min_bpm: 149, max_bpm: 156 },
  { zone: 4, min_bpm: 156, max_bpm: 176 },
  { zone: 5, min_bpm: 176, max_bpm: 220 }
];

/** One sample a second: `secs` seconds at `value` each, for each [secs, value]. */
function stream(...parts: [number, number][]) {
  const values: number[] = [];
  for (const [secs, v] of parts) for (let i = 0; i < secs; i++) values.push(v);
  return { values, time: values.map((_, i) => i), step: 1 };
}

describe('targetWindow', () => {
  it('puts a ±5% FTP window around a power target', () => {
    expect(targetWindow({ name: 'Main', duration_minutes: 20, target_power_percent_ftp: 88 }, 'power', 280, ZONES)).toEqual({
      lo: 230,
      hi: 260,
      zone: 3,
      label: 'Z3 · 230–260 W'
    });
  });

  it('uses the athlete zone for heart rate, from an HR zone or a power target', () => {
    expect(targetWindow({ name: 'Warmup', duration_minutes: 10, target_hr_zone: 2 }, 'hr', 280, ZONES)?.label).toBe('Z2 · 136–148 bpm');
    expect(targetWindow({ name: 'Main', duration_minutes: 10, target_power_percent_ftp: 100 }, 'hr', 280, ZONES)?.label).toBe('Z4 · 156–175 bpm');
    expect(targetWindow({ name: 'Easy', duration_minutes: 5, target_hr_zone: 1 }, 'hr', 280, ZONES)?.label).toBe('Z1 · < 136 bpm');
  });

  it('maps an HR-zone block to the power zone when judging power', () => {
    expect(targetWindow({ name: 'Steady', duration_minutes: 60, target_hr_zone: 2 }, 'power', 280, ZONES)?.label).toBe('Z2 · 155–210 W');
  });

  it('has no window without a target, FTP or zones', () => {
    expect(targetWindow({ name: 'Strength', duration_minutes: 30 }, 'power', 280, ZONES)).toBeNull();
    expect(targetWindow({ name: 'Main', duration_minutes: 30, target_power_percent_ftp: 90 }, 'power', 0, ZONES)).toBeNull();
    expect(targetWindow({ name: 'Main', duration_minutes: 30, target_hr_zone: 2 }, 'hr', 280, [])).toBeNull();
  });
});

describe('blockStats', () => {
  const w = { lo: 230, hi: 260, zone: 3, label: '' };

  it('splits the block into below, in and above target and averages it', () => {
    // 15 minute block: 5 min below, 5 min in, 5 min above. Power is judged on a 30-s rolling
    // average, so each boundary moves by a few seconds.
    const s = blockStats(stream([300, 200], [300, 245], [300, 280]), 0, 15, w, 'power');
    expect(s).toMatchObject({ secs: 900, fitSecs: 900, min: 200, max: 280 });
    expect(s.below).toBeGreaterThanOrEqual(300);
    expect(s.below).toBeLessThan(330);
    expect(s.inn).toBeGreaterThan(270);
    expect(s.above).toBeGreaterThan(270);
    expect(s.below + s.inn + s.above).toBe(900);
    expect(s.avg).toBe(Math.round((200 + 245 + 280) / 3));
  });

  it('judges heart rate sample by sample', () => {
    const hr = { lo: 156, hi: 176, zone: 4, label: '' };
    const s = blockStats(stream([60, 165], [30, 150], [30, 165]), 0, 2, hr, 'hr');
    expect(s.below).toBe(30);
  });

  it("ignores heart rate's first 60 s of each block while it catches up", () => {
    const hr = { lo: 156, hi: 176, zone: 4, label: '' };
    const s = blockStats(stream([60, 140], [60, 165]), 0, 2, hr, 'hr');
    expect(s.fitSecs).toBe(60);
    expect(s.below).toBe(0);
    expect(s.inn).toBe(60);
  });

  it('only counts samples inside the block', () => {
    const s = blockStats(stream([60, 100], [60, 245]), 1, 1, w, 'power');
    expect(s.secs).toBe(60);
    expect(s.inn).toBe(60);
  });
});

describe('pvaBlocks / inTargetPct', () => {
  const structure = [
    { name: 'Warmup', duration_minutes: 1, target_hr_zone: 1 },
    { name: 'Main', duration_minutes: 2, target_power_percent_ftp: 88 },
    { name: 'Notes', duration_minutes: 0 }
  ];

  it('lays the blocks out end to end and skips zero-length ones', () => {
    const blocks = pvaBlocks(structure, stream([60, 120], [120, 245]), 'power', 280, ZONES);
    expect(blocks.map((b) => [b.name, b.t0, b.min])).toEqual([
      ['Warmup', 0, 1],
      ['Main', 1, 2]
    ]);
    expect(inTargetPct(blocks)).toBe(100);
  });

  it('marks a stopped-early block as not done', () => {
    const blocks = pvaBlocks(structure, stream([60, 120]), 'power', 280, ZONES);
    expect(blocks[1].stats.secs).toBe(0);
    expect(blocks[1].stats.avg).toBeNull();
  });

  it('has no in-target share without a stream', () => {
    expect(inTargetPct(pvaBlocks(structure, {}, 'power', 280, ZONES))).toBeNull();
  });
});

describe('chart helpers', () => {
  it('colours each trace point by its block', () => {
    const blocks = pvaBlocks([{ name: 'Main', duration_minutes: 2, target_power_percent_ftp: 88 }], stream([60, 300], [60, 245]), 'power', 280, ZONES);
    const pts = tracePoints(stream([60, 300], [60, 245]), blocks, 2);
    expect(pts.map((p) => p.fit)).toEqual(['above', 'in']);
  });

  it('scales the y axis from FTP or the HR zones', () => {
    expect(yRange('power', 280, ZONES)).toEqual([98, 350]);
    expect(yRange('hr', 280, ZONES)).toEqual([101, 191]);
    expect(yRange('hr', 280, [])).toEqual([100, 200]);
  });

  it('gives five power bands and the athlete HR bands', () => {
    expect(zoneBands('power', 200, ZONES).map((b) => b.zone)).toEqual([1, 2, 3, 4, 5]);
    expect(zoneBands('hr', 200, ZONES)[1]).toEqual({ zone: 2, lo: 136, hi: 149 });
  });

  it('formats minutes like the design', () => {
    expect(mins(54.4)).toBe('54′');
    expect(mins(65)).toBe('1h05');
  });
});

describe('hrOnPowerScale ("Both")', () => {
  // ZONES: Z2 136–149 bpm; power Z2 at FTP 200 is 112–150 W.
  it('draws a heart rate inside the matching power zone band', () => {
    const mid = hrOnPowerScale(142.5, 200, ZONES)!;
    expect(mid).toBeCloseTo(112 + 0.5 * (150 - 112), 5);
    // Z4 HR lands in the Z4 power band, Z1 HR in Z1.
    const z4 = hrOnPowerScale(166, 200, ZONES)!;
    expect(z4).toBeGreaterThanOrEqual(182);
    expect(z4).toBeLessThanOrEqual(210);
    expect(hrOnPowerScale(120, 200, ZONES)!).toBeLessThan(112);
  });

  it('keeps a higher heart rate higher on the chart', () => {
    const vals = [110, 130, 140, 150, 160, 180, 200].map((v) => hrOnPowerScale(v, 200, ZONES)!);
    expect([...vals].sort((a, b) => a - b)).toEqual(vals);
  });

  it('needs HR zones and an FTP', () => {
    expect(hrOnPowerScale(150, 200, [])).toBeNull();
    expect(hrOnPowerScale(150, 0, ZONES)).toBeNull();
  });
});

describe('power is judged on a 30-s rolling average', () => {
  it('counts a steady ride with noisy second-by-second power as in target', () => {
    // 172 W average alternating 160 / 184 every second: half the raw seconds sit below a
    // 170-195 W window, the effort itself doesn't.
    const values = Array.from({ length: 600 }, (_, i) => (i % 2 ? 184 : 160));
    const s = blockStats({ values, time: values.map((_, i) => i), step: 1 }, 0, 10, { lo: 170, hi: 195, zone: 2, label: '' }, 'power');
    expect(s.avg).toBe(172);
    expect(s.inn / s.fitSecs).toBeGreaterThan(0.95);
  });

  it('still catches a sustained drop', () => {
    const values = [...Array(300).fill(180), ...Array(300).fill(150)];
    const s = blockStats({ values, time: values.map((_, i) => i), step: 1 }, 0, 10, { lo: 170, hi: 195, zone: 2, label: '' }, 'power');
    expect(s.below / s.fitSecs).toBeGreaterThan(0.4);
  });

  it('averages over time, not sample count', () => {
    expect(rollingMean([{ t: 0, dt: 1, v: 100 }, { t: 1, dt: 1, v: 200 }], 30)).toEqual([100, 150]);
  });
});
