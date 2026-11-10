import { describe, expect, it } from 'vitest';
import type { HeartRateDay } from '$lib/types/heartRate';
import {
  buildDayModel,
  chartPath,
  clockAt,
  chartY,
  formatMins,
  rangeStats,
  restFloor,
  restingVsAverage,
  tickMinutes,
  zoneMinutes,
  zoomPresets
} from './heartDay';

const START = '2026-11-08T05:00:00Z';
const at = (min: number) => new Date(Date.parse(START) + min * 60_000).toISOString();

function day(over: Partial<HeartRateDay> = {}): HeartRateDay {
  return {
    date: '2026-11-08',
    day_start: START,
    day_end: '2026-11-09T05:00:00Z',
    source: 'garmin',
    interval_sec: 120,
    resting_hr: 50,
    min_hr: 50,
    max_hr: 150,
    avg_hr: 80,
    samples: [],
    workouts: [],
    sleep: [],
    resting_hr_history: [],
    ...over
  };
}

describe('buildDayModel', () => {
  it('spreads 2-minute samples over the minutes they stand for and leaves holes empty', () => {
    const m = buildDayModel(day({ samples: [{ t: at(0), bpm: 60 }, { t: at(2), bpm: 62 }, { t: at(30), bpm: 70 }] }));
    expect(m.len).toBe(1440);
    expect(m.hr.slice(0, 4)).toEqual([60, 60, 62, 62]);
    // a 28-minute hole: the sample before it covers at most 5 minutes
    expect(m.hr.slice(4, 8)).toEqual([62, 62, 62, null]);
    expect(m.hr.slice(30, 33)).toEqual([70, 70, null]);
  });

  it('clips sleep and workouts to the day and labels detections and naps', () => {
    const m = buildDayModel(
      day({
        sleep: [
          { started_at: at(-120), ended_at: at(400), is_nap: false },
          { started_at: at(800), ended_at: at(840), is_nap: true }
        ],
        workouts: [
          { id: 'w1', source: 'garmin', sport: 'run', title: 'Easy run', started_at: at(500), ended_at: at(545), duration_seconds: 2700, avg_hr: 140, max_hr: 150, strain_score: 10, tss: 30, detected: false },
          { id: 'w2', source: 'hr_detected', sport: 'other', title: null, started_at: at(1000), ended_at: null, duration_seconds: 1200, avg_hr: 120, max_hr: 130, strain_score: 5, tss: 8, detected: true }
        ]
      })
    );
    expect(m.spans.map((s) => [s.kind, s.a, s.b, s.title])).toEqual([
      ['sleep', 0, 400, 'Sleep'],
      ['workout', 500, 545, 'Easy run'],
      ['sleep', 800, 840, 'Nap'],
      ['detected', 1000, 1020, 'Detected activity']
    ]);
  });

  it('handles a 25-hour clock-change day', () => {
    expect(buildDayModel(day({ day_end: '2026-11-09T06:00:00Z' })).len).toBe(1500);
  });
});

describe('stats, path, zones', () => {
  const hr = [null, 60, 70, null, 80];

  it('rangeStats ignores gaps', () => {
    expect(rangeStats(hr, 0, 5)).toEqual({ avg: 70, max: 80, min: 60, n: 3 });
    expect(rangeStats(hr, 0, 1)).toEqual({ avg: null, max: null, min: null, n: 0 });
  });

  it('chartPath breaks the line at gaps', () => {
    const d = chartPath(hr, 0, 5, (v) => v);
    expect(d.match(/M/g)?.length).toBe(2);
    expect(d.startsWith('M300.0 60.0L500.0 70.0M900.0 80.0')).toBe(true);
  });

  it('chartY clamps to the axis', () => {
    expect(chartY(35)).toBe(200);
    expect(chartY(185)).toBe(0);
    expect(chartY(250)).toBe(0);
  });

  it('zoneMinutes counts only minutes at or above the rest floor', () => {
    const zones = [
      { zone: 1, min: 0, max: 130 },
      { zone: 2, min: 130, max: 150 },
      { zone: 3, min: 150, max: 999 }
    ];
    expect(zoneMinutes([90, 110, 135, 160, null], 0, 5, zones, 100)).toEqual({ 1: 1, 2: 1, 3: 1 });
    expect(restFloor(200)).toBe(100);
    expect(restFloor(null)).toBe(100);
  });

  it('ticks and durations', () => {
    expect(tickMinutes(0, 1440)).toEqual([0, 180, 360, 540, 720, 900, 1080, 1260, 1440]);
    expect(tickMinutes(500, 560)).toEqual([510, 525, 540, 555]);
    expect(formatMins(45)).toBe('45m');
    expect(formatMins(125)).toBe('2h 05');
  });
});

describe('zoomPresets / restingVsAverage', () => {
  it('offers overnight and each workout', () => {
    const m = buildDayModel(
      day({
        sleep: [{ started_at: at(-60), ended_at: at(420), is_nap: false }],
        workouts: [{ id: 'w', source: 'garmin', sport: 'run', title: 'Run', started_at: at(600), ended_at: at(640), duration_seconds: 2400, avg_hr: 1, max_hr: 1, strain_score: 1, tss: 1, detected: false }]
      })
    );
    expect(zoomPresets(m)).toEqual([
      { label: 'Whole day', r: null },
      { label: 'Overnight', r: [0, 450] },
      { label: 'Run', r: [585, 655] }
    ]);
  });

  it('compares resting HR with the prior average', () => {
    const h = [
      { date: '2026-11-05', resting_hr: 52 },
      { date: '2026-11-06', resting_hr: 50 },
      { date: '2026-11-07', resting_hr: 51 },
      { date: '2026-11-08', resting_hr: 48 }
    ];
    expect(restingVsAverage(h, '2026-11-08')).toBe(-3);
    expect(restingVsAverage(h.slice(2), '2026-11-08')).toBeNull();
  });
});

describe('fractional-minute ranges (zoom bounds from second-precision timestamps)', () => {
  const hr = Array.from({ length: 20 }, (_, i) => 100 + i);

  it('chartPath still draws', () => {
    expect(chartPath(hr, 2.6, 9.4, (v) => v)).toMatch(/^M/);
  });

  it('zoneMinutes still counts', () => {
    const zones = [{ zone: 1, min: 0, max: 999 }];
    expect(zoneMinutes(hr, 2.6, 9.4, zones, 0)[1]).toBe(8);
  });

  it('spans are whole minutes', () => {
    const m = buildDayModel(
      day({ workouts: [{ id: 'w', source: 'garmin', sport: 'walk', title: 'Walk', started_at: '2026-11-08T17:37:24Z', ended_at: '2026-11-08T18:15:10Z', duration_seconds: 2266, avg_hr: 1, max_hr: 1, strain_score: 1, tss: 1, detected: false }] })
    );
    expect([m.spans[0].a, m.spans[0].b]).toEqual([757, 795]);
  });
});

describe('labels', () => {
  it('compact ticks halve the count', () => {
    expect(tickMinutes(0, 1440, true)).toEqual([0, 360, 720, 1080, 1440]);
  });

  it('detection chips carry their start time', () => {
    const m = buildDayModel(
      day({ workouts: [{ id: 'd', source: 'hr_detected', sport: 'other', title: 'Detected activity', started_at: at(600), ended_at: at(640), duration_seconds: 2400, avg_hr: 1, max_hr: 1, strain_score: 1, tss: 1, detected: true }] })
    );
    const label = zoomPresets(m).find((z) => z.label.startsWith('Detected'))?.label;
    expect(label).toMatch(/^Detected · \d\d:\d\d$/);
  });
});

describe('clockAt', () => {
  it('counts from the athlete’s midnight, whatever the device time zone', () => {
    expect(clockAt(0)).toBe('00:00');
    expect(clockAt(754)).toBe('12:34');
    expect(clockAt(1440)).toBe('00:00');
  });
});
