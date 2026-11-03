import { describe, expect, it } from 'vitest';
import {
  activityMeta,
  formatHoursMinutes,
  getDurationSecs,
  getHrZonePctsTopDown,
  getWorkoutLabel,
  hasAnyHrZone,
  positiveRounded,
  sampleRateLabel,
  splitDistance,
  splitPace,
  splitSpeed,
  splitTime,
  sportGlyph,
  streamChannels,
  weekEyebrow
} from './trainingFormat';

describe('trainingFormat', () => {
  it('labels sports and glyphs', () => {
    expect(getWorkoutLabel('strength_training')).toBe('Strength');
    expect(getWorkoutLabel('ride')).toBe('Ride');
    expect(getWorkoutLabel(undefined)).toBe('Workout');
    expect(sportGlyph('Cycling')).toBe('BIKE');
    expect(sportGlyph('yoga')).toBe('OTHER');
  });

  it('reads duration from seconds or start/end', () => {
    expect(getDurationSecs({ duration_seconds: 3600.7 })).toBe(3600);
    expect(getDurationSecs({ started_at: '2026-11-02T07:00:00Z', ended_at: '2026-11-02T08:30:00Z' })).toBe(5400);
    expect(getDurationSecs({})).toBe(0);
    expect(formatHoursMinutes(5100)).toBe('1h 25m');
    expect(formatHoursMinutes(2520)).toBe('42m');
  });

  it('builds row meta in the athlete units', () => {
    const w = { started_at: '2026-11-02T12:00:00', duration_seconds: 5100, distance_m: 44257, norm_power_w: 244 };
    expect(activityMeta(w, 'metric')).toBe('Mon 2 Nov · 1h 25m · 44.3 km · 244 W NP');
    expect(activityMeta(w, 'imperial')).toContain('27.5 mi');
  });

  it('orders zones top-down and detects missing zones', () => {
    const w = { hr_zone_1_pct: 10, hr_zone_2_pct: 20, hr_zone_3_pct: 30, hr_zone_4_pct: 25, hr_zone_5_pct: 15 };
    expect(getHrZonePctsTopDown(w)).toEqual([15, 25, 30, 20, 10]);
    expect(hasAnyHrZone({})).toBe(false);
  });

  it('formats split cells', () => {
    expect(splitTime(3725)).toBe('1:02:05');
    expect(splitTime(305)).toBe('5:05');
    expect(splitDistance(1609.344, 'imperial')).toBe('1.0');
    expect(splitDistance(0, 'metric')).toBe('—');
    expect(splitPace(301)).toBe('5:01');
    expect(splitSpeed({ distance: 1000, elapsed_time: 100 }, 'metric')).toBe('36.0');
  });

  it('rounds positive values only', () => {
    expect(positiveRounded(91.6)).toBe(92);
    expect(positiveRounded(0)).toBeNull();
    expect(positiveRounded('x')).toBeNull();
  });

  it('labels the ISO week', () => {
    expect(weekEyebrow(new Date(2026, 10, 2), true)).toBe('WEEK 45 · THIS WEEK');
    expect(weekEyebrow(new Date(2026, 9, 26), false)).toBe('WEEK 44');
  });

  it('lists stored stream channels and the sample rate', () => {
    const streams = { resolution_seconds: 1, time_series: { heartrate: [1, 2], watts: [1], latlng: [[0, 0], [1, 1]] } };
    expect(streamChannels(streams as any)).toEqual(['Heart rate', 'GPS']);
    expect(sampleRateLabel(streams as any)).toBe('1 s');
    expect(streamChannels(null)).toEqual([]);
    expect(sampleRateLabel({ resolution_seconds: 0 } as any)).toBeNull();
  });
});
