/**
 * Pure helpers for the wide Plan screen (design: Plan · month week + inspector).
 * Everything here maps real `/v1/training-plans` rows; nothing is sample data.
 */
import { addDays, endOfMonth, endOfWeek, format, startOfMonth, startOfWeek } from 'date-fns';
import type { Interval, Workout, WorkoutZone } from '$lib/types/training';
import { WEEK_STARTS_ON } from '$lib/utils/week';

export type WideStep = { name: string; minutes: number; zone: number; target?: string };
export type WideBar = { minutes: number; pct: number; hard: boolean };

export type WideSession = {
  /** training_plans.id (rows from /v1/training-plans are always real plan rows). */
  id: string;
  isoDate: string;
  title: string;
  sport: Workout['sport'];
  durationMin: number;
  tss: number | null;
  /** 1–5 from primary_zone, 0 for strength / mobility (no zone chip colour). */
  zone: number;
  completed: boolean;
  /** Recorded workout that completed it (null when done by hand or not done). */
  completedWorkoutId: string | null;
  context: string;
  steps: WideStep[];
  bars: WideBar[];
};

const PRIMARY_ZONE: Record<WorkoutZone, number> = {
  Recovery: 1,
  Endurance: 2,
  Tempo: 3,
  Threshold: 4,
  VO2Max: 5,
  Anaerobic: 5
};

/** Bar height (% of the profile) for an HR-zone target with no power target. */
const HR_ZONE_PCT: Record<number, number> = { 1: 50, 2: 65, 3: 80, 4: 92, 5: 100 };

export function zoneFromPercentFtp(pct: number): number {
  return pct < 56 ? 1 : pct < 76 ? 2 : pct < 91 ? 3 : pct < 106 ? 4 : 5;
}

function stepZone(i: Interval): number {
  if (typeof i.target_power_percent_ftp === 'number') return zoneFromPercentFtp(i.target_power_percent_ftp);
  if (typeof i.target_hr_zone === 'number') return Math.min(5, Math.max(1, Math.round(i.target_hr_zone)));
  return 0;
}

/** Design duration style: 45′, 1h25, 3h. */
export function fmtDur(min: number): string {
  const m = Math.max(0, Math.round(min));
  if (m < 60) return `${m}′`;
  const rest = m % 60;
  return `${Math.floor(m / 60)}h${rest ? String(rest).padStart(2, '0') : ''}`;
}

/** "14H 20M" for summary lines. */
export function fmtHoursMinutes(min: number): string {
  const m = Math.max(0, Math.round(min));
  return `${Math.floor(m / 60)}H ${m % 60}M`;
}

function stepTarget(i: Interval, ftp: number): string | undefined {
  const pct = i.target_power_percent_ftp;
  if (typeof pct === 'number') {
    // Prescribed targets are one % of FTP; show the usual ±2.5 % working band (as the phone sheet).
    if (ftp > 0) return `${Math.round((ftp * (pct - 2.5)) / 100)}–${Math.round((ftp * (pct + 2.5)) / 100)} W`;
    return `${pct}% FTP`;
  }
  if (typeof i.target_hr_zone === 'number') return `Z${i.target_hr_zone} HR`;
  return undefined;
}

export function toWideSession(w: Workout, ftp = 0): WideSession {
  const intervals = (w.structure ?? []).filter(Boolean);
  const steps: WideStep[] = intervals.map((i) => ({
    name: i.name || 'Step',
    minutes: Math.max(0, Number(i.duration_minutes) || 0),
    zone: stepZone(i),
    target: stepTarget(i, ftp)
  }));
  const bars: WideBar[] = intervals.map((i) => {
    const pct =
      typeof i.target_power_percent_ftp === 'number'
        ? Math.min(100, Math.max(8, i.target_power_percent_ftp))
        : typeof i.target_hr_zone === 'number'
          ? HR_ZONE_PCT[Math.min(5, Math.max(1, Math.round(i.target_hr_zone)))]
          : 40;
    return { minutes: Math.max(1, Number(i.duration_minutes) || 0), pct, hard: pct > 85 };
  });
  const isStrength = w.sport === 'strength' || w.sport === 'mobility';
  const stepMinutes = steps.reduce((a, s) => a + s.minutes, 0);
  return {
    id: w.id,
    isoDate: w.date,
    title: w.title || 'Session',
    sport: w.sport,
    durationMin: Number(w.duration_minutes) > 0 ? Number(w.duration_minutes) : stepMinutes,
    tss: Number(w.projected_tss) > 0 ? Number(w.projected_tss) : null,
    zone: isStrength ? 0 : (PRIMARY_ZONE[w.primary_zone] ?? 0),
    completed: Boolean(w.completed),
    completedWorkoutId: w.completed_workout_id ?? null,
    context: w.description ?? '',
    steps,
    bars
  };
}

/** Sessions grouped by yyyy-MM-dd, each day in title order. */
export function groupByIso(sessions: WideSession[]): Record<string, WideSession[]> {
  const out: Record<string, WideSession[]> = {};
  for (const s of sessions) (out[s.isoDate] ??= []).push(s);
  for (const k of Object.keys(out)) out[k].sort((a, b) => a.title.localeCompare(b.title));
  return out;
}

/** Sunday-first weeks covering `month` (first row may start in the previous month). */
export function monthWeeks(month: Date): Date[][] {
  const start = startOfWeek(startOfMonth(month), { weekStartsOn: WEEK_STARTS_ON });
  const end = endOfWeek(endOfMonth(month), { weekStartsOn: WEEK_STARTS_ON });
  const weeks: Date[][] = [];
  for (let d = start; d <= end; d = addDays(d, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, i) => addDays(d, i)));
  }
  return weeks;
}

export function weekDaysFrom(weekStart: Date): Date[] {
  return Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
}

export function totals(days: Date[], byIso: Record<string, WideSession[]>): { tss: number; minutes: number; count: number } {
  let tss = 0;
  let minutes = 0;
  let count = 0;
  for (const d of days) {
    for (const s of byIso[format(d, 'yyyy-MM-dd')] ?? []) {
      tss += s.tss ?? 0;
      minutes += s.durationMin;
      count += 1;
    }
  }
  return { tss, minutes, count };
}

/** A session can be moved when it is not done yet and its day isn't in the past. */
export function isMovable(s: WideSession, todayIso: string): boolean {
  return !s.completed && s.isoDate >= todayIso;
}

/**
 * Schedule changes for putting `from` on `toIso`: swap with the first movable session
 * already there (the design's drag swaps days), else a plain move. Null when not allowed.
 */
export function planDrop(
  from: WideSession,
  toIso: string,
  byIso: Record<string, WideSession[]>,
  todayIso: string
): { id: string; date: string }[] | null {
  if (!isMovable(from, todayIso) || toIso < todayIso || toIso === from.isoDate) return null;
  const other = (byIso[toIso] ?? []).find((s) => s.id !== from.id && isMovable(s, todayIso));
  if (other) {
    return [
      { id: from.id, date: toIso },
      { id: other.id, date: from.isoDate }
    ];
  }
  return [{ id: from.id, date: toIso }];
}

/** Undo for a set of changes: every moved session back to the date it had before. */
export function inverseChanges(
  changes: { id: string; date: string }[],
  before: Record<string, string>
): { id: string; date: string }[] {
  return changes.filter((c) => before[c.id]).map((c) => ({ id: c.id, date: before[c.id] }));
}
