import { describe, expect, it } from 'vitest';
import {
  buildPacePoints,
  crosshairXpx,
  downsamplePoints,
  filterLapMarkersForDisplay,
  formatTimeAxis,
  hrToZone,
  isMovingIndex,
  lapMarkers,
  lapXpx,
  nearestTime,
  nearestTimeIndex,
  nearestTimeOnTimeline,
  splitByTimeGaps,
  splitZoneRuns,
  zip,
  zoneRunsWithGaps,
  type Point
} from './streamChartsPrep';

describe('isMovingIndex', () => {
  it('true when moving array is missing/empty', () => {
    expect(isMovingIndex(0)).toBe(true);
    expect(isMovingIndex(0, [])).toBe(true);
  });
  it('true unless explicitly false', () => {
    expect(isMovingIndex(0, [true, false])).toBe(true);
    expect(isMovingIndex(1, [true, false])).toBe(false);
  });
});

describe('zip', () => {
  it('empty when either input is missing/empty', () => {
    expect(zip(undefined, [1, 2])).toEqual([]);
    expect(zip([1, 2], undefined)).toEqual([]);
    expect(zip([], [])).toEqual([]);
  });
  it('zips to the shorter length, skips null/non-finite values', () => {
    expect(zip([1, 2, 3], [10, null as any, NaN])).toEqual([{ t: 1, v: 10 }]);
  });
  it('filters by requireMoving', () => {
    const result = zip([1, 2], [10, 20], { requireMoving: true, moving: [true, false] });
    expect(result).toEqual([{ t: 1, v: 10 }]);
  });
  it('filters by min/max value', () => {
    const result = zip([1, 2, 3], [5, 15, 25], { minValue: 10, maxValue: 20 });
    expect(result).toEqual([{ t: 2, v: 15 }]);
  });
});

describe('buildPacePoints', () => {
  it('empty when time/velocity missing', () => {
    expect(buildPacePoints(undefined, [1], 'run')).toEqual([]);
  });
  it('run: computes sec/km pace and skips slow/implausible values', () => {
    const result = buildPacePoints([0, 1], [4, 0.1], 'run');
    expect(result).toEqual([{ t: 0, v: 250 }]);
  });
  it('row: computes sec/500m pace with a higher velocity floor', () => {
    const result = buildPacePoints([0, 1], [5, 0.5], 'row');
    expect(result).toEqual([{ t: 0, v: 100 }]);
  });
  it('skips non-moving indices', () => {
    const result = buildPacePoints([0, 1], [4, 4], 'run', [true, false]);
    expect(result).toEqual([{ t: 0, v: 250 }]);
  });
  it('excludes paces slower than the sport cap', () => {
    // run cap is 600s/km; a very slow but still-valid velocity should be dropped
    const result = buildPacePoints([0], [1000 / 601], 'run');
    expect(result).toEqual([]);
  });
});

describe('hrToZone', () => {
  it('classifies each band boundary', () => {
    expect(hrToZone(100)).toBe(1);
    expect(hrToZone(138)).toBe(2);
    expect(hrToZone(154)).toBe(2);
    expect(hrToZone(155)).toBe(3);
    expect(hrToZone(167)).toBe(3);
    expect(hrToZone(168)).toBe(4);
    expect(hrToZone(177)).toBe(4);
    expect(hrToZone(178)).toBe(5);
  });
});

describe('splitZoneRuns', () => {
  it('empty input returns empty output', () => {
    expect(splitZoneRuns([])).toEqual([]);
  });
  it('single run when zone never changes', () => {
    const points = [
      { t: 0, v: 100, zone: 2, color: '#x' },
      { t: 1, v: 101, zone: 2, color: '#x' }
    ];
    const result = splitZoneRuns(points);
    expect(result).toHaveLength(1);
    expect(result[0].data).toHaveLength(2);
  });
  it('splits into multiple runs on zone change with a bridge point', () => {
    const points = [
      { t: 0, v: 100, zone: 1, color: '#a' },
      { t: 1, v: 140, zone: 2, color: '#b' },
      { t: 2, v: 145, zone: 2, color: '#b' }
    ];
    const result = splitZoneRuns(points);
    expect(result).toHaveLength(2);
    expect(result[0].zone).toBe(1);
    expect(result[1].zone).toBe(2);
    // bridge point (t=1) appears at the end of the first run and start of the second
    expect(result[0].data[result[0].data.length - 1].t).toBe(1);
    expect(result[1].data[0].t).toBe(1);
  });
});

describe('splitByTimeGaps', () => {
  it('empty input returns empty output', () => {
    expect(splitByTimeGaps([])).toEqual([]);
  });
  it('single segment when no gaps exceed the threshold', () => {
    const points: Point[] = [{ t: 0, v: 1 }, { t: 10, v: 2 }, { t: 20, v: 3 }];
    expect(splitByTimeGaps(points)).toEqual([points]);
  });
  it('splits into multiple segments on large gaps', () => {
    const points: Point[] = [{ t: 0, v: 1 }, { t: 10, v: 2 }, { t: 100, v: 3 }];
    const result = splitByTimeGaps(points, 30);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual([{ t: 0, v: 1 }, { t: 10, v: 2 }]);
    expect(result[1]).toEqual([{ t: 100, v: 3 }]);
  });
});

describe('lapMarkers', () => {
  const streams = { time_series: { time: [0, 10, 20, 30] }, resolution_seconds: 1 } as any;

  it('empty when no time stream', () => {
    expect(lapMarkers({ time_series: {}, resolution_seconds: 1 } as any, [])).toEqual([]);
  });
  it('skips laps with missing/non-positive lap_index', () => {
    const laps = [{ lap_index: 0, start_index: 1 }, { lap_index: undefined, start_index: 2 }] as any;
    expect(lapMarkers(streams, laps)).toEqual([]);
  });
  it('maps lap start_index to a time value, defaulting start_index to 0', () => {
    const laps = [{ lap_index: 1, start_index: 2 }, { lap_index: 2 }] as any;
    expect(lapMarkers(streams, laps)).toEqual([
      { lapIndex: 1, t: 20 },
      { lapIndex: 2, t: 0 }
    ]);
  });
});

describe('formatTimeAxis', () => {
  it('under an hour shows Nm', () => {
    expect(formatTimeAxis(45, 45)).toBe('45m');
  });
  it('an hour or more shows h:mm', () => {
    expect(formatTimeAxis(90, 90)).toBe('1:30');
  });
});

describe('nearestTime / nearestTimeOnTimeline / nearestTimeIndex', () => {
  const points: Point[] = [{ t: 0, v: 1 }, { t: 10, v: 2 }, { t: 25, v: 3 }];
  const time = [0, 10, 25];

  it('nearestTime: empty returns null', () => {
    expect(nearestTime([], 5)).toBeNull();
  });
  it('nearestTime: finds closest point time', () => {
    expect(nearestTime(points, 12)).toBe(10);
  });
  it('nearestTimeOnTimeline: empty returns null', () => {
    expect(nearestTimeOnTimeline(5, [])).toBeNull();
  });
  it('nearestTimeOnTimeline: finds closest timeline value', () => {
    expect(nearestTimeOnTimeline(22, time)).toBe(25);
  });
  it('nearestTimeIndex: empty returns null', () => {
    expect(nearestTimeIndex(5, [])).toBeNull();
  });
  it('nearestTimeIndex: finds closest index', () => {
    expect(nearestTimeIndex(22, time)).toBe(2);
  });
});

describe('filterLapMarkersForDisplay', () => {
  it('returns markers unchanged when <= 12', () => {
    const markers = Array.from({ length: 12 }, (_, i) => ({ lapIndex: i + 1, t: i * 10 }));
    expect(filterLapMarkersForDisplay(markers)).toEqual(markers);
  });
  it('thins markers beyond 12, always keeping the last', () => {
    const markers = Array.from({ length: 20 }, (_, i) => ({ lapIndex: i + 1, t: i * 10 }));
    const result = filterLapMarkersForDisplay(markers);
    expect(result.length).toBeLessThan(markers.length);
    const last = markers[markers.length - 1];
    expect(result.some((m) => m.lapIndex === last.lapIndex && m.t === last.t)).toBe(true);
  });
});

describe('lapXpx / crosshairXpx', () => {
  it('returns CHART_LEFT when maxTMin <= 0', () => {
    expect(lapXpx(30, 0, 500)).toBe(40);
  });
  it('scales proportionally within the chart width', () => {
    const x = lapXpx(30, 1, 500); // 30s = 0.5min of a 1min-wide chart
    expect(x).toBeCloseTo(40 + 0.5 * 500, 5);
  });
  it('crosshairXpx delegates to lapXpx', () => {
    expect(crosshairXpx(30, 1, 500)).toBe(lapXpx(30, 1, 500));
  });
});

describe('zoneRunsWithGaps', () => {
  it('drops single-point segments after gap splitting', () => {
    const zoned = [
      { t: 0, v: 100, zone: 1, color: '#a' },
      { t: 100, v: 101, zone: 1, color: '#a' } // big gap -> isolated single point on each side
    ];
    const result = zoneRunsWithGaps(zoned);
    expect(result).toEqual([]);
  });
  it('keeps multi-point segments', () => {
    const zoned = [
      { t: 0, v: 100, zone: 1, color: '#a' },
      { t: 1, v: 101, zone: 1, color: '#a' },
      { t: 2, v: 102, zone: 1, color: '#a' }
    ];
    const result = zoneRunsWithGaps(zoned);
    expect(result).toHaveLength(1);
    expect(result[0].data).toHaveLength(3);
  });
});

describe('downsamplePoints', () => {
  it('passthrough when resolution is not 1s', () => {
    const pts: Point[] = Array.from({ length: 2000 }, (_, i) => ({ t: i, v: i }));
    expect(downsamplePoints(pts, 5)).toBe(pts);
  });
  it('passthrough when under the max point count', () => {
    const pts: Point[] = [{ t: 0, v: 0 }];
    expect(downsamplePoints(pts, 1, 1000)).toBe(pts);
  });
  it('downsamples by taking every other point when over the max', () => {
    const pts: Point[] = Array.from({ length: 10 }, (_, i) => ({ t: i, v: i }));
    const result = downsamplePoints(pts, 1, 5);
    expect(result).toEqual([{ t: 0, v: 0 }, { t: 2, v: 2 }, { t: 4, v: 4 }, { t: 6, v: 6 }, { t: 8, v: 8 }]);
  });
});
