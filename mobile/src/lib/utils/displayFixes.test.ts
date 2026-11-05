import { describe, expect, it } from 'vitest';
import { formatHoursMinutes, splitPace, weekEyebrow } from './trainingFormat';
import { bpmRangeLabel, hrZoneAnchorLabel } from '$lib/hrZoneDisplay';
import { workoutMeta } from './linking';

describe('display fixes from the app audit', () => {
  it('never shows 60 minutes or 60 seconds', () => {
    expect(formatHoursMinutes(7170)).toBe('2h 00m'); // 1h 59m 30s
    expect(formatHoursMinutes(3540)).toBe('59m');
    expect(splitPace(299.6)).toBe('5:00');
    expect(splitPace(301)).toBe('5:01');
  });

  it('labels a week by its dates, not a week number', () => {
    expect(weekEyebrow(new Date(2026, 10, 1), true)).toBe('1 – 7 NOV · THIS WEEK'); // Sun 1 Nov 2026
    expect(weekEyebrow(new Date(2026, 9, 25), false)).toBe('25 – 31 OCT');
    expect(weekEyebrow(new Date(2026, 9, 29), false)).toBe('29 OCT – 4 NOV');
  });

  it('shows [min, max) zone edges as the athlete reads them', () => {
    expect(bpmRangeLabel(0, 143, 'bpm')).toBe('< 143 bpm');
    expect(bpmRangeLabel(143, 158)).toBe('143–157');
    expect(bpmRangeLabel(188, 999)).toBe('≥ 188');
  });

  it('labels zones with what they are built from', () => {
    expect(hrZoneAnchorLabel({ hr_zones: { anchor_label: 'Max HR 204 / RHR 52 bpm' }, lthr: 185 })).toBe('Max HR 204 / RHR 52');
    expect(hrZoneAnchorLabel({ lthr: 185 })).toBe('LTHR 185');
    expect(hrZoneAnchorLabel(null)).toBeNull();
  });

  it('follows the 12h setting in linked-workout rows', () => {
    const w = { started_at: '2026-11-04T18:14:00', duration_seconds: 3600, tss: 38 };
    expect(workoutMeta(w, '12h')).toContain('6:14 PM');
    expect(workoutMeta(w, '24h')).toContain('18:14');
  });
});
