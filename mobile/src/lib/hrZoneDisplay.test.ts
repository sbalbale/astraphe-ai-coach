import { describe, expect, it } from 'vitest';
import {
  bpmToHrZone,
  canonicalHrZoneShortName,
  formatHrZoneTitle,
  formatZoneBpmRange,
  hrZoneColorForBpm,
  HR_ZONE_HEX,
  HR_ZONE_MISSING_HEX,
  HR_ZONE_NEUTRAL_HEX,
  mergeWorkoutZoneDefs,
  profileZonesToActivityZones,
  sortZoneDefs
} from './hrZoneDisplay';

const zones = [
  { zone: 1, name: 'Recovery', min_bpm: 0, max_bpm: 120 },
  { zone: 2, name: 'Endurance', min_bpm: 120, max_bpm: 140 },
  { zone: 3, name: 'Tempo', min_bpm: 140, max_bpm: 160 },
  { zone: 4, name: 'Threshold', min_bpm: 160, max_bpm: 180 },
  { zone: 5, name: 'VO2max+', min_bpm: 180, max_bpm: 999 }
];

describe('formatHrZoneTitle', () => {
  it('formats a known zone', () => {
    expect(formatHrZoneTitle(3)).toBe('Z3 · Tempo');
  });
  it('empty string for unknown zone', () => {
    expect(formatHrZoneTitle(9)).toBe('');
  });
});

describe('canonicalHrZoneShortName', () => {
  it('returns known label', () => {
    expect(canonicalHrZoneShortName(1)).toBe('Recovery');
  });
  it('empty string for unknown zone', () => {
    expect(canonicalHrZoneShortName(0)).toBe('');
  });
});

describe('profileZonesToActivityZones', () => {
  it('empty/null returns empty array', () => {
    expect(profileZonesToActivityZones(null)).toEqual([]);
    expect(profileZonesToActivityZones([])).toEqual([]);
  });
  it('maps and sorts by zone', () => {
    const result = profileZonesToActivityZones([
      { zone: 2, name: 'Endurance', min: 120, max: 140 },
      { zone: 1, name: 'Recovery', min: 0, max: 120 }
    ]);
    expect(result[0].zone).toBe(1);
    expect(result[0].min_bpm).toBe(0);
  });
});

describe('sortZoneDefs', () => {
  it('sorts ascending without mutating input', () => {
    const input = [zones[2], zones[0]];
    const sorted = sortZoneDefs(input);
    expect(sorted[0].zone).toBe(1);
    expect(input[0].zone).toBe(3); // unchanged
  });
});

describe('bpmToHrZone', () => {
  it('null/non-finite/non-positive bpm returns 0', () => {
    expect(bpmToHrZone(zones, null)).toBe(0);
    expect(bpmToHrZone(zones, NaN)).toBe(0);
    expect(bpmToHrZone(zones, 0)).toBe(0);
  });
  it('empty zones returns 0', () => {
    expect(bpmToHrZone([], 150)).toBe(0);
  });
  it('classifies within a zone band', () => {
    expect(bpmToHrZone(zones, 150)).toBe(3);
  });
  it('bpm at/above last zone min returns last zone', () => {
    expect(bpmToHrZone(zones, 999)).toBe(5);
  });
});

describe('hrZoneColorForBpm', () => {
  it('neutral color when zone 0 but zones exist', () => {
    expect(hrZoneColorForBpm(zones, -5)).toBe(HR_ZONE_NEUTRAL_HEX);
  });
  it('missing color when no zones at all', () => {
    expect(hrZoneColorForBpm([], 150)).toBe(HR_ZONE_MISSING_HEX);
  });
  it('zone hex color for a matched zone', () => {
    expect(hrZoneColorForBpm(zones, 150)).toBe(HR_ZONE_HEX[3]);
  });
});

describe('mergeWorkoutZoneDefs', () => {
  it('prefers activity zones when present', () => {
    const result = mergeWorkoutZoneDefs(zones, null);
    expect(result).toHaveLength(5);
  });
  it('falls back to profile zones when activity zones missing', () => {
    const result = mergeWorkoutZoneDefs(null, [{ zone: 1, name: 'Recovery', min: 0, max: 120 }]);
    expect(result).toHaveLength(1);
  });
  it('falls back to empty array when both missing', () => {
    expect(mergeWorkoutZoneDefs(null, null)).toEqual([]);
  });
});

describe('formatZoneBpmRange', () => {
  it('null zone returns em dash', () => {
    expect(formatZoneBpmRange(null)).toBe('—');
  });
  it('open-ended top zone uses + suffix', () => {
    expect(formatZoneBpmRange(zones[4])).toBe('180+ bpm');
  });
  it('bounded zone shows range', () => {
    expect(formatZoneBpmRange(zones[1])).toBe('120–140 bpm');
  });
});
