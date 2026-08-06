import { describe, expect, it } from 'vitest';
import {
  cmToFtIn,
  cmToIn,
  convertPace,
  elevationFromMeters,
  elevationUnitLabel,
  formatElevationMeters,
  formatSecondsToPace,
  formatSegmentDistance,
  formatWorkoutDistance,
  ftInToCm,
  inToCm,
  kgToLb,
  kgToLbRoundedHalf,
  lbToKg,
  normalizeUnits,
  parsePaceToSeconds,
  roundToStep,
  workoutDistanceParts
} from './units';

describe('normalizeUnits', () => {
  it('detects imperial', () => {
    expect(normalizeUnits('Imperial')).toBe('imperial');
  });
  it('defaults to metric for non-imperial/non-string', () => {
    expect(normalizeUnits('metric')).toBe('metric');
    expect(normalizeUnits(undefined)).toBe('metric');
    expect(normalizeUnits(42)).toBe('metric');
  });
});

describe('roundToStep', () => {
  it('rounds to nearest step', () => {
    expect(roundToStep(72.3, 0.5)).toBe(72.5);
  });
  it('returns 0 for non-finite or non-positive step', () => {
    expect(roundToStep(NaN, 0.5)).toBe(0);
    expect(roundToStep(72, 0)).toBe(0);
    expect(roundToStep(72, -1)).toBe(0);
  });
});

describe('kg/lb conversions', () => {
  it('kgToLb converts', () => {
    expect(kgToLb(10)).toBeCloseTo(22.046, 2);
  });
  it('kgToLb non-finite returns 0', () => {
    expect(kgToLb(NaN)).toBe(0);
  });
  it('kgToLbRoundedHalf rounds to nearest half pound', () => {
    expect(kgToLbRoundedHalf(1)).toBe(2);
  });
  it('lbToKg converts', () => {
    expect(lbToKg(22.0462)).toBeCloseTo(10, 2);
  });
  it('lbToKg non-finite returns 0', () => {
    expect(lbToKg(NaN)).toBe(0);
  });
});

describe('formatSegmentDistance', () => {
  it('rowing always uses meters', () => {
    expect(formatSegmentDistance(500, 'imperial', 'row')).toBe('500m');
    expect(formatSegmentDistance(500, 'imperial', 'rowing')).toBe('500m');
  });
  it('null/non-finite returns em dash', () => {
    expect(formatSegmentDistance(null, 'metric', 'run')).toBe('—');
    expect(formatSegmentDistance(NaN, 'metric', 'run')).toBe('—');
  });
  it('delegates to formatWorkoutDistance for non-rowing sports', () => {
    expect(formatSegmentDistance(2000, 'metric', 'run')).toBe('2.00 km');
  });
});

describe('elevationUnitLabel', () => {
  it('ft for imperial, m for metric', () => {
    expect(elevationUnitLabel('imperial')).toBe('ft');
    expect(elevationUnitLabel('metric')).toBe('m');
  });
});

describe('elevationFromMeters', () => {
  it('converts to feet for imperial', () => {
    expect(elevationFromMeters(100, 'imperial')).toBeCloseTo(328.08, 1);
  });
  it('metric passthrough', () => {
    expect(elevationFromMeters(100, 'metric')).toBe(100);
  });
  it('non-finite returns 0', () => {
    expect(elevationFromMeters(NaN, 'metric')).toBe(0);
  });
});

describe('formatElevationMeters', () => {
  it('null/non-finite returns em dash', () => {
    expect(formatElevationMeters(null, 'metric')).toBe('—');
  });
  it('imperial formats feet', () => {
    expect(formatElevationMeters(100, 'imperial')).toBe('328 ft');
  });
  it('metric formats meters', () => {
    expect(formatElevationMeters(100.6, 'metric')).toBe('101 m');
  });
});

describe('formatWorkoutDistance', () => {
  it('null/non-finite returns em dash', () => {
    expect(formatWorkoutDistance(null, 'metric')).toBe('—');
  });
  it('rowing always meters regardless of units', () => {
    expect(formatWorkoutDistance(500, 'metric', 'rowing')).toBe('500m');
  });
  it('swim imperial under a mile shows yards', () => {
    expect(formatWorkoutDistance(500, 'imperial', 'swim')).toBe('547 yd');
  });
  it('swim imperial over a mile shows miles', () => {
    expect(formatWorkoutDistance(2000, 'imperial', 'swimming')).toBe('1.24 mi');
  });
  it('imperial non-swim shows miles', () => {
    expect(formatWorkoutDistance(1609.344, 'imperial', 'run')).toBe('1.00 mi');
  });
  it('metric under 1km shows meters', () => {
    expect(formatWorkoutDistance(500, 'metric', 'run')).toBe('500 m');
  });
  it('metric over 1km shows km', () => {
    expect(formatWorkoutDistance(2500, 'metric', 'bike')).toBe('2.50 km');
  });
});

describe('workoutDistanceParts', () => {
  it('null/non-finite returns em dash parts', () => {
    expect(workoutDistanceParts(null, 'metric')).toEqual({ value: '—', unit: '' });
  });
  it('rowing returns meters', () => {
    expect(workoutDistanceParts(500, 'metric', 'row')).toEqual({ value: '500', unit: 'm' });
  });
  it('swim imperial under a mile returns yards', () => {
    expect(workoutDistanceParts(500, 'imperial', 'swim')).toEqual({ value: '547', unit: 'yd' });
  });
  it('swim imperial over a mile returns miles', () => {
    const result = workoutDistanceParts(2000, 'imperial', 'swim');
    expect(result.unit).toBe('mi');
  });
  it('imperial non-swim returns miles', () => {
    expect(workoutDistanceParts(1609.344, 'imperial', 'run')).toEqual({ value: '1.00', unit: 'mi' });
  });
  it('metric under 1km returns meters', () => {
    expect(workoutDistanceParts(500, 'metric', 'run')).toEqual({ value: '500', unit: 'm' });
  });
  it('metric over 1km returns km', () => {
    expect(workoutDistanceParts(2500, 'metric', 'run')).toEqual({ value: '2.50', unit: 'km' });
  });
});

describe('parsePaceToSeconds', () => {
  it('parses m:ss', () => {
    expect(parsePaceToSeconds('4:30')).toBe(270);
  });
  it('trims whitespace', () => {
    expect(parsePaceToSeconds('  4:30  ')).toBe(270);
  });
  it('rejects malformed strings', () => {
    expect(parsePaceToSeconds('abc')).toBeNull();
    expect(parsePaceToSeconds('4:5')).toBeNull();
  });
  it('rejects out-of-range seconds', () => {
    expect(parsePaceToSeconds('4:60')).toBeNull();
  });
});

describe('formatSecondsToPace', () => {
  it('formats seconds', () => {
    expect(formatSecondsToPace(270)).toBe('4:30');
  });
  it('clamps negative/NaN to 0', () => {
    expect(formatSecondsToPace(-5)).toBe('0:00');
    expect(formatSecondsToPace(NaN)).toBe('0:00');
  });
});

describe('convertPace', () => {
  it('same units passthrough', () => {
    expect(convertPace('4:30', 'metric', 'metric')).toBe('4:30');
  });
  it('unparseable pace passthrough', () => {
    expect(convertPace('bad', 'metric', 'imperial')).toBe('bad');
  });
  it('metric to imperial', () => {
    const result = convertPace('4:00', 'metric', 'imperial');
    expect(result).not.toBe('4:00');
  });
  it('imperial to metric', () => {
    const result = convertPace('6:26', 'imperial', 'metric');
    expect(result).not.toBe('6:26');
  });
});

describe('cm/in conversions', () => {
  it('cmToIn converts', () => {
    expect(cmToIn(2.54)).toBeCloseTo(1, 5);
  });
  it('cmToIn non-finite returns 0', () => {
    expect(cmToIn(NaN)).toBe(0);
  });
  it('inToCm converts', () => {
    expect(inToCm(1)).toBeCloseTo(2.54, 5);
  });
  it('inToCm non-finite returns 0', () => {
    expect(inToCm(NaN)).toBe(0);
  });
  it('cmToFtIn splits feet and inches', () => {
    expect(cmToFtIn(180)).toEqual({ ft: 5, inch: 11 });
  });
  it('ftInToCm combines feet and inches', () => {
    expect(ftInToCm(5, 11)).toBeCloseTo(180.34, 1);
  });
  it('ftInToCm clamps negative inputs to 0', () => {
    expect(ftInToCm(-1, -5)).toBe(0);
  });
});
