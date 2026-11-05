import { describe, expect, it } from 'vitest';
import { format } from 'date-fns';
import type { Workout } from '$lib/types/training';
import {
  fmtDur,
  fmtHoursMinutes,
  groupByIso,
  inverseChanges,
  isMovable,
  monthWeeks,
  planDrop,
  toWideSession,
  totals,
  weekDaysFrom,
  zoneFromPercentFtp
} from './planWide';

function wk(over: Partial<Workout> = {}): Workout {
  return {
    id: 'a',
    date: '2026-11-05',
    title: 'Sweet spot',
    sport: 'bike',
    primary_zone: 'Threshold',
    duration_minutes: 85,
    projected_tss: 92,
    description: 'Build sustained power.',
    structure: [
      { name: 'Warm-up', duration_minutes: 15, target_power_percent_ftp: 60 },
      { name: 'Block', duration_minutes: 12, target_power_percent_ftp: 92 },
      { name: 'Easy', duration_minutes: 10, target_hr_zone: 1 }
    ],
    completed: false,
    ...over
  };
}

describe('planWide', () => {
  it('formats durations like the design', () => {
    expect(fmtDur(45)).toBe('45′');
    expect(fmtDur(85)).toBe('1h25');
    expect(fmtDur(240)).toBe('4h');
    expect(fmtHoursMinutes(500)).toBe('8H 20M');
  });

  it('maps %FTP to zones', () => {
    expect(zoneFromPercentFtp(50)).toBe(1);
    expect(zoneFromPercentFtp(70)).toBe(2);
    expect(zoneFromPercentFtp(85)).toBe(3);
    expect(zoneFromPercentFtp(95)).toBe(4);
    expect(zoneFromPercentFtp(110)).toBe(5);
  });

  it('builds a session with watt targets, zones and profile bars', () => {
    const s = toWideSession(wk(), 262);
    expect(s.zone).toBe(4);
    expect(s.tss).toBe(92);
    expect(s.steps[1]).toEqual({ name: 'Block', minutes: 12, zone: 4, target: '230–255 W' });
    expect(s.steps[2].target).toBe('Z1 HR');
    expect(s.bars.map((b) => b.hard)).toEqual([false, true, false]);
  });

  it('falls back to %FTP without an FTP, and has no zone for strength', () => {
    expect(toWideSession(wk()).steps[0].target).toBe('60% FTP');
    expect(toWideSession(wk({ sport: 'strength' })).zone).toBe(0);
    expect(toWideSession(wk({ projected_tss: 0 })).tss).toBeNull();
  });

  it('builds Sunday-first month weeks', () => {
    const weeks = monthWeeks(new Date(2026, 10, 1)); // November 2026 starts on a Sunday
    expect(format(weeks[0][0], 'yyyy-MM-dd')).toBe('2026-11-01');
    expect(weeks.every((w) => w.length === 7)).toBe(true);
    expect(format(weeks[weeks.length - 1][6], 'yyyy-MM-dd')).toBe('2026-12-05');
  });

  it('totals a week', () => {
    const byIso = groupByIso([toWideSession(wk()), toWideSession(wk({ id: 'b', date: '2026-11-06', projected_tss: 40, duration_minutes: 40 }))]);
    expect(totals(weekDaysFrom(new Date(2026, 10, 2)), byIso)).toEqual({ tss: 132, minutes: 125, count: 2 });
  });

  it('plans a drop as a move, or a swap when the day has a movable session', () => {
    const a = toWideSession(wk());
    const b = toWideSession(wk({ id: 'b', date: '2026-11-07' }));
    const byIso = groupByIso([a, b]);
    const today = '2026-11-03';
    expect(planDrop(a, '2026-11-06', byIso, today)).toEqual([{ id: 'a', date: '2026-11-06' }]);
    expect(planDrop(a, '2026-11-07', byIso, today)).toEqual([
      { id: 'a', date: '2026-11-07' },
      { id: 'b', date: '2026-11-05' }
    ]);
    expect(planDrop(a, '2026-11-02', byIso, today)).toBeNull(); // past day
    expect(planDrop(a, a.isoDate, byIso, today)).toBeNull();
  });

  it('never moves completed or past sessions', () => {
    const today = '2026-11-03';
    expect(isMovable(toWideSession(wk({ completed: true })), today)).toBe(false);
    expect(isMovable(toWideSession(wk({ date: '2026-11-01' })), today)).toBe(false);
  });

  it('inverts changes for undo', () => {
    expect(
      inverseChanges(
        [
          { id: 'a', date: '2026-11-07' },
          { id: 'b', date: '2026-11-05' }
        ],
        { a: '2026-11-05', b: '2026-11-07' }
      )
    ).toEqual([
      { id: 'a', date: '2026-11-05' },
      { id: 'b', date: '2026-11-07' }
    ]);
  });
});
