import { describe, expect, it } from 'vitest';
import {
  daySessions,
  moveChanges,
  profileBars,
  readinessStatus,
  sessionTarget,
  shortDuration,
  statDuration,
  weekSummary
} from './todayWide';

describe('profileBars', () => {
  it('draws blocks like the Plan sheet: width by duration, height by %FTP, colour by zone', () => {
    const bars = profileBars({
      duration_minutes: 50,
      primary_zone: 'Threshold',
      structure: [
        { name: 'Warm-up', duration_minutes: 10, target_power_percent_ftp: 60 },
        { name: 'Block', duration_minutes: 12, target_power_percent_ftp: 95 },
        { name: 'Easy', duration_minutes: 5, target_hr_zone: 1 },
        { name: 'Tempo', duration_minutes: 13, target_power_percent_ftp: 80 },
        { name: 'Cool down', duration_minutes: 10 }
      ]
    });
    expect(bars.map((b) => b.zone)).toEqual([2, 4, 1, 3, 0]);
    // 95% FTP → 78 px of the 96 px chart, as on the Plan sheet.
    expect(bars[1]).toMatchObject({ grow: 12, pct: 81.3 });
    expect(bars[0].pct).toBeLessThan(bars[3].pct);
  });

  it('falls back to one bar at the session zone, and none for no session', () => {
    expect(profileBars({ duration_minutes: 90, primary_zone: 'Endurance', structure: [] })).toHaveLength(1);
    expect(profileBars(null)).toEqual([]);
  });
});

describe('formatting', () => {
  it('formats durations', () => {
    expect(shortDuration(45)).toBe('45′');
    expect(shortDuration(60)).toBe('1h');
    expect(shortDuration(85)).toBe('1h 25m');
    expect(statDuration(85)).toBe('85 min');
    expect(statDuration(240)).toBe('4 h');
  });

  it('shows a watt range for bike sessions with FTP, else the zone', () => {
    const w = { sport: 'bike' as const, primary_zone: 'Threshold' as const, structure: [{ name: 'b', duration_minutes: 12, target_power_percent_ftp: 90 }] };
    expect(sessionTarget(w, 262)).toBe('229–242 W'); // 90% ±2.5, as on the Plan sheet
    expect(sessionTarget(w, 0)).toBe('Z4 HR');
    expect(sessionTarget({ ...w, sport: 'run' }, 262)).toBe('Z4 HR');
  });

  it('sums the week', () => {
    expect(weekSummary([{ projected_tss: 92, duration_minutes: 85 }, { projected_tss: 64, duration_minutes: 90 }])).toBe(
      '156 TSS · 2H 55M PLANNED'
    );
  });

  it('labels readiness', () => {
    expect(readinessStatus(null).tone).toBe('muted');
    expect(readinessStatus(80).label).toBe('Good to train');
    expect(readinessStatus(65).label).toBe('Train as planned');
    expect(readinessStatus(20).tone).toBe('red');
  });
});

describe('moveChanges', () => {
  const week = [
    { id: 'a', date: '2026-11-02', completed: false },
    { id: 'b', date: '2026-11-04', completed: false },
    { id: 'c', date: '2026-11-05', completed: true }
  ];

  it('moves to a free day', () => {
    expect(moveChanges(week[0], '2026-11-03', week)).toEqual([{ id: 'a', date: '2026-11-03' }]);
  });

  it('swaps with the target day session', () => {
    expect(moveChanges(week[0], '2026-11-04', week)).toEqual([
      { id: 'a', date: '2026-11-04' },
      { id: 'b', date: '2026-11-02' }
    ]);
  });

  it('does not move a completed session out of its day', () => {
    expect(moveChanges(week[0], '2026-11-05', week)).toEqual([{ id: 'a', date: '2026-11-05' }]);
  });

  it('is a no-op for the same day', () => {
    expect(moveChanges(week[0], '2026-11-02', week)).toEqual([]);
  });
});

describe('daySessions', () => {
  it("lists every session on the day, hardest first", () => {
    const ws = [
      { id: 'st', date: '2026-11-03', projected_tss: 30, duration_minutes: 60 },
      { id: 'tank', date: '2026-11-03', projected_tss: 94, duration_minutes: 60 },
      { id: 'other-day', date: '2026-11-04', projected_tss: 200, duration_minutes: 90 }
    ];
    expect(daySessions(ws, '2026-11-03').map((w) => w.id)).toEqual(['tank', 'st']);
    expect(daySessions(ws, '2026-11-05')).toEqual([]);
  });
});
