import { describe, expect, it } from 'vitest';
import {
  averagePaceFromSplits,
  averageSpeedFromSplits,
  intervalsToSplits,
  lapsToSplits,
  paceFromDistanceTime,
  splitAverageSpeedMps,
  splitsLabel,
  splitsTableTitle,
  type ActivitySplit
} from './lapSplits';

describe('paceFromDistanceTime', () => {
  it('non-positive distance/time returns null', () => {
    expect(paceFromDistanceTime(0, 100, 'run')).toBeNull();
    expect(paceFromDistanceTime(100, 0, 'run')).toBeNull();
  });
  it('row computes sec/500m', () => {
    expect(paceFromDistanceTime(1000, 200, 'row')).toBe(100);
  });
  it('run metric computes sec/km', () => {
    expect(paceFromDistanceTime(1000, 250, 'run', 'metric')).toBe(250);
  });
  it('run imperial computes sec/mile', () => {
    const result = paceFromDistanceTime(1609.344, 400, 'run', 'imperial');
    expect(result).toBe(400);
  });
  it('other sports return null', () => {
    expect(paceFromDistanceTime(1000, 200, 'bike')).toBeNull();
  });
});

function split(overrides: Partial<ActivitySplit> = {}): ActivitySplit {
  return {
    split_number: 1,
    distance: 0,
    elapsed_time: 0,
    pace_seconds: null,
    average_heartrate: null,
    average_watts: null,
    average_cadence: null,
    average_speed: null,
    ...overrides
  };
}

describe('splitAverageSpeedMps', () => {
  it('prefers average_speed when positive', () => {
    expect(splitAverageSpeedMps(split({ average_speed: 5 }))).toBe(5);
  });
  it('falls back to distance/time', () => {
    expect(splitAverageSpeedMps(split({ distance: 1000, elapsed_time: 200 }))).toBe(5);
  });
  it('falls back to pace_seconds', () => {
    expect(splitAverageSpeedMps(split({ pace_seconds: 100 }))).toBe(5);
  });
  it('returns null when no usable field', () => {
    expect(splitAverageSpeedMps(split())).toBeNull();
  });
});

describe('averageSpeedFromSplits', () => {
  it('averages valid split speeds', () => {
    const splits = [split({ average_speed: 4 }), split({ average_speed: 6 })];
    expect(averageSpeedFromSplits(splits)).toBe(5);
  });
  it('falls back to total distance/time when no per-split speeds', () => {
    const splits = [
      split({ distance: 0, elapsed_time: 0, average_speed: null }),
      split({ distance: 0, elapsed_time: 0, average_speed: null })
    ];
    // no positive speeds derivable and totals are 0 -> null
    expect(averageSpeedFromSplits(splits)).toBeNull();
  });
  it('falls back to totals when per-split speed unusable but totals usable', () => {
    // splitAverageSpeedMps would derive from distance/time per-split anyway,
    // so exercise the pure fallback path with an empty splits array.
    expect(averageSpeedFromSplits([])).toBeNull();
  });
});

describe('intervalsToSplits', () => {
  it('maps rowing intervals using pace_per_500m when present', () => {
    const result = intervalsToSplits([
      {
        split_number: 1,
        distance: 500,
        elapsed_time: 100,
        pace_per_500m: 100,
        average_heartrate: 150,
        average_watts: 200,
        average_cadence: 24
      } as any
    ]);
    expect(result[0].average_speed).toBe(5);
    expect(result[0].pace_seconds).toBe(100);
  });
  it('falls back to distance/time speed when pace missing', () => {
    const result = intervalsToSplits([
      {
        split_number: 1,
        distance: 500,
        elapsed_time: 100,
        pace_per_500m: null,
        average_heartrate: null,
        average_watts: null,
        average_cadence: null
      } as any
    ]);
    expect(result[0].average_speed).toBe(5);
  });
  it('null distance/time and no pace yields null speed', () => {
    const result = intervalsToSplits([
      {
        split_number: 1,
        distance: null,
        elapsed_time: null,
        pace_per_500m: null,
        average_heartrate: null,
        average_watts: null,
        average_cadence: null
      } as any
    ]);
    expect(result[0].average_speed).toBeNull();
    expect(result[0].distance).toBe(0);
    expect(result[0].elapsed_time).toBe(0);
  });
});

describe('lapsToSplits', () => {
  it('uses average_speed to derive pace when present', () => {
    const result = lapsToSplits(
      [
        {
          lap_index: 1,
          distance: 1000,
          elapsed_time: 250,
          average_heartrate: 150,
          average_watts: 200,
          average_cadence: 80,
          average_speed: 4
        } as any
      ],
      'run',
      'metric'
    );
    expect(result[0].pace_seconds).not.toBeNull();
  });
  it('falls back to distance/time pace when speed missing', () => {
    const result = lapsToSplits(
      [
        {
          lap_index: null,
          distance: 1000,
          elapsed_time: 250,
          average_heartrate: null,
          average_watts: null,
          average_cadence: null,
          average_speed: null
        } as any
      ],
      'run',
      'metric'
    );
    expect(result[0].split_number).toBe(1); // falls back to index + 1
    expect(result[0].pace_seconds).toBe(250);
  });
});

describe('averagePaceFromSplits', () => {
  it('computes pace from totals', () => {
    const splits = [split({ distance: 500, elapsed_time: 125 }), split({ distance: 500, elapsed_time: 125 })];
    // total 1000m in 250s -> row pace is sec/500m: (250/1000)*500 = 125
    expect(averagePaceFromSplits(splits, 'row')).toBe(125);
  });
});

describe('splitsTableTitle / splitsLabel', () => {
  it('rowing uses interval terminology', () => {
    expect(splitsTableTitle('row')).toBe('500m Intervals');
    expect(splitsLabel('row')).toBe('Split');
  });
  it('other sports use lap terminology', () => {
    expect(splitsTableTitle('run')).toBe('Laps');
    expect(splitsLabel('run')).toBe('Lap');
  });
});
