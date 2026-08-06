import { describe, expect, it } from 'vitest';
import {
  cadenceChartTitle,
  cadenceColumnHeader,
  cadenceUnitLabel,
  clampPaceSeries,
  coercePaceSport,
  formatPaceAxisTick,
  formatPaceSeconds,
  formatPaceWithSuffix,
  formatSpeedFromMps,
  invertedPaceYScale,
  normalizeMeasurementUnits,
  paceChartTitle,
  paceDistanceSuffix,
  paceSecondsFromVelocity,
  speedFromMps,
  speedUnitLabel,
  supportsPaceChart
} from './paceChart';

describe('speedFromMps / speedUnitLabel', () => {
  it('converts m/s to km/h for metric', () => {
    expect(speedFromMps(10, 'metric')).toBeCloseTo(36, 5);
  });
  it('converts m/s to mph for imperial', () => {
    expect(speedFromMps(10, 'imperial')).toBeCloseTo(22.37, 1);
  });
  it('non-finite returns 0', () => {
    expect(speedFromMps(NaN, 'metric')).toBe(0);
  });
  it('unit labels', () => {
    expect(speedUnitLabel('metric')).toBe('km/h');
    expect(speedUnitLabel('imperial')).toBe('mph');
  });
});

describe('formatSpeedFromMps', () => {
  it('null/non-finite/non-positive returns em dash', () => {
    expect(formatSpeedFromMps(null, 'metric')).toBe('—');
    expect(formatSpeedFromMps(0, 'metric')).toBe('—');
    expect(formatSpeedFromMps(NaN, 'metric')).toBe('—');
  });
  it('formats with unit suffix', () => {
    expect(formatSpeedFromMps(10, 'metric')).toBe('36.0 km/h');
  });
});

describe('coercePaceSport', () => {
  it('maps known sport strings', () => {
    expect(coercePaceSport('Rowing')).toBe('row');
    expect(coercePaceSport('running')).toBe('run');
    expect(coercePaceSport('ride')).toBe('bike');
  });
  it('unknown sport is other', () => {
    expect(coercePaceSport('yoga')).toBe('other');
  });
});

describe('cadence helpers', () => {
  it('row/run use spm', () => {
    expect(cadenceUnitLabel('row')).toBe('spm');
    expect(cadenceUnitLabel('run')).toBe('spm');
  });
  it('bike uses rpm', () => {
    expect(cadenceUnitLabel('bike')).toBe('rpm');
  });
  it('chart title differs for rowing', () => {
    expect(cadenceChartTitle('row')).toBe('Stroke Rate');
    expect(cadenceChartTitle('bike')).toBe('Cadence');
  });
  it('column header includes unit', () => {
    expect(cadenceColumnHeader('bike')).toBe('Cadence (rpm)');
  });
});

describe('supportsPaceChart', () => {
  it('true for row/run', () => {
    expect(supportsPaceChart('row')).toBe(true);
    expect(supportsPaceChart('run')).toBe(true);
  });
  it('false for bike', () => {
    expect(supportsPaceChart('bike')).toBe(false);
  });
});

describe('paceSecondsFromVelocity', () => {
  it('non-finite/non-positive returns null', () => {
    expect(paceSecondsFromVelocity(NaN, 'run')).toBeNull();
    expect(paceSecondsFromVelocity(0, 'run')).toBeNull();
  });
  it('row computes sec/500m', () => {
    expect(paceSecondsFromVelocity(5, 'row')).toBe(100);
  });
  it('row returns null when implausibly slow', () => {
    expect(paceSecondsFromVelocity(0.5, 'row')).toBeNull();
  });
  it('run metric computes sec/km', () => {
    expect(paceSecondsFromVelocity(4, 'run', 'metric')).toBe(250);
  });
  it('run imperial computes sec/mile', () => {
    const result = paceSecondsFromVelocity(4, 'run', 'imperial');
    expect(result).toBeCloseTo(402.336, 2);
  });
  it('run returns null when implausibly slow', () => {
    expect(paceSecondsFromVelocity(0.1, 'run', 'metric')).toBeNull();
  });
  it('other sports return null', () => {
    expect(paceSecondsFromVelocity(5, 'bike')).toBeNull();
  });
});

describe('paceDistanceSuffix / paceChartTitle', () => {
  it('row suffix', () => {
    expect(paceDistanceSuffix('row')).toBe('/500m');
  });
  it('run suffix depends on units', () => {
    expect(paceDistanceSuffix('run', 'metric')).toBe('/km');
    expect(paceDistanceSuffix('run', 'imperial')).toBe('/mi');
  });
  it('other sports have no suffix', () => {
    expect(paceDistanceSuffix('bike')).toBe('');
  });
  it('chart title includes suffix when present', () => {
    expect(paceChartTitle('row')).toBe('Pace /500m');
    expect(paceChartTitle('bike')).toBe('Pace');
  });
});

describe('formatPaceSeconds / formatPaceWithSuffix', () => {
  it('null/non-finite returns em dash', () => {
    expect(formatPaceSeconds(null)).toBe('—');
    expect(formatPaceSeconds(NaN)).toBe('—');
  });
  it('formats m:ss', () => {
    expect(formatPaceSeconds(270)).toBe('4:30');
  });
  it('formatPaceWithSuffix appends distance suffix', () => {
    expect(formatPaceWithSuffix(270, 'run', 'metric')).toBe('4:30/km');
  });
  it('formatPaceWithSuffix passes through em dash unchanged', () => {
    expect(formatPaceWithSuffix(null, 'run', 'metric')).toBe('—');
  });
});

describe('normalizeMeasurementUnits', () => {
  it('delegates to normalizeUnits', () => {
    expect(normalizeMeasurementUnits('Imperial')).toBe('imperial');
    expect(normalizeMeasurementUnits(undefined)).toBe('metric');
  });
});

describe('clampPaceSeries', () => {
  it('empty array returns default bounds', () => {
    expect(clampPaceSeries([])).toEqual({ clamped: [], lo: 0, hi: 1 });
  });
  it('clamps outliers to the quantile bounds', () => {
    const values = [200, 201, 202, 203, 204, 205, 206, 207, 208, 1000];
    const result = clampPaceSeries(values);
    expect(Math.max(...result.clamped)).toBeLessThanOrEqual(result.hi);
    expect(Math.min(...result.clamped)).toBeGreaterThanOrEqual(result.lo);
    expect(result.clamped).toHaveLength(values.length);
  });
});

describe('invertedPaceYScale', () => {
  it('maps larger pace-seconds (slower) toward the bottom, smaller (faster) toward the top', () => {
    // Domain is padded beyond [yMin, yMax], so scale(yMax) isn't exactly 0 nor
    // scale(yMin) exactly chartHeight -- assert the inverted direction instead.
    const scale = invertedPaceYScale(100, 200, 400);
    expect(scale(200)).toBeGreaterThan(scale(100));
    expect(scale(100)).toBeGreaterThan(0);
    expect(scale(200)).toBeLessThan(400);
  });
});

describe('formatPaceAxisTick', () => {
  it('formats a tick value as m:ss', () => {
    expect(formatPaceAxisTick(270)).toBe('4:30');
  });
});
