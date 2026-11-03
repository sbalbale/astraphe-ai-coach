/**
 * Pure helpers for the wide Trends & zones page (design: WTrends): weekly buckets of
 * training load, ramp rate, and time-in-zone for a week or month.
 */
import { addDays, addMonths, differenceInCalendarDays, endOfMonth, format, startOfMonth, startOfWeek } from 'date-fns';
import { workoutDurationSecs } from '$lib/utils/workoutDuration';
import { WEEK_STARTS_ON } from '$lib/utils/week';

export type LoadRow = { date: string; ctl?: number; atl?: number; tsb?: number; daily_tss?: number };
export type PlannedRow = { date: string; projected_tss?: number | null };

export type WeekBucket = {
  start: Date;
  tss: number;
  planned: number;
  /** End-of-week (or latest) fitness / fatigue; null when the week has no load rows. */
  ctl: number | null;
  atl: number | null;
  current: boolean;
};

const num = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const day = (iso: string) => new Date(`${iso}T00:00:00`);

/** Monday of the week `weeksBack` weeks before the week containing `today`. */
export function rangeStart(today: Date, weeks: number): Date {
  return addDays(startOfWeek(today, { weekStartsOn: WEEK_STARTS_ON }), -(weeks - 1) * 7);
}

/** `weeks` Sunday-start buckets ending with the current week, oldest first. */
export function weeklyBuckets(rows: LoadRow[], planned: PlannedRow[], weeks: number, today: Date): WeekBucket[] {
  const first = rangeStart(today, weeks);
  const buckets: WeekBucket[] = Array.from({ length: weeks }, (_, i) => ({
    start: addDays(first, i * 7),
    tss: 0,
    planned: 0,
    ctl: null,
    atl: null,
    current: i === weeks - 1
  }));
  // Calendar days, not ms: a week with a DST change is an hour short.
  const indexOf = (d: Date) => Math.floor(differenceInCalendarDays(d, first) / 7);
  const sorted = [...rows].filter((r) => r?.date).sort((a, b) => a.date.localeCompare(b.date));
  for (const r of sorted) {
    const i = indexOf(day(r.date));
    if (i < 0 || i >= weeks) continue;
    buckets[i].tss += num(r.daily_tss);
    buckets[i].ctl = num(r.ctl);
    buckets[i].atl = num(r.atl);
  }
  for (const p of planned) {
    if (!p?.date) continue;
    const i = indexOf(day(p.date));
    if (i >= 0 && i < weeks) buckets[i].planned += num(p.projected_tss);
  }
  for (let i = 0; i < weeks; i++) {
    const b = buckets[i];
    b.tss = Math.round(b.tss);
    b.planned = Math.round(b.planned);
  }
  return buckets;
}

/** Fitness change per week over the last 28 days of rows; null without enough history. */
export function rampRatePerWeek(rows: LoadRow[]): number | null {
  const sorted = [...rows].filter((r) => r?.date).sort((a, b) => a.date.localeCompare(b.date));
  if (sorted.length < 2) return null;
  const last = sorted[sorted.length - 1];
  const target = format(addDays(day(last.date), -28), 'yyyy-MM-dd');
  const then = sorted.find((r) => r.date >= target);
  if (!then || then === last || differenceInCalendarDays(day(last.date), day(then.date)) < 21) return null;
  const weeks = differenceInCalendarDays(day(last.date), day(then.date)) / 7;
  return Math.round(((num(last.ctl) - num(then.ctl)) / weeks) * 10) / 10;
}

/** Average TSS of completed (non-current) weeks that had any load. */
export function averageCompletedTss(buckets: WeekBucket[]): number {
  const done = buckets.filter((b) => !b.current && b.tss > 0);
  return done.length ? Math.round(done.reduce((a, b) => a + b.tss, 0) / done.length) : 0;
}

export type ZonePeriod = 'week' | 'month';

/** [start, end] (inclusive dates) of the week / month `offset` periods from the current one. */
export function zoneWindow(period: ZonePeriod, offset: number, today: Date): { start: Date; end: Date } {
  if (period === 'month') {
    const m = addMonths(startOfMonth(today), offset);
    return { start: m, end: endOfMonth(m) };
  }
  const start = addDays(startOfWeek(today, { weekStartsOn: WEEK_STARTS_ON }), offset * 7);
  return { start, end: new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6, 23, 59, 59, 999) };
}

type ZoneWorkout = Record<string, unknown> & { started_at?: string | null };

/** Seconds in HR zones 1–5 for workouts that started inside the window (with zone data). */
export function zoneSecondsInWindow(workouts: ZoneWorkout[], start: Date, end: Date): number[] {
  const totals = [0, 0, 0, 0, 0];
  for (const w of workouts) {
    if (!w?.started_at) continue;
    const t = new Date(w.started_at).getTime();
    if (!Number.isFinite(t) || t < start.getTime() || t > end.getTime()) continue;
    if (w.hr_zone_1_pct === null || w.hr_zone_1_pct === undefined) continue;
    const secs = workoutDurationSecs(w) ?? 0;
    for (let z = 0; z < 5; z++) totals[z] += (secs * num(w[`hr_zone_${z + 1}_pct`])) / 100;
  }
  return totals;
}

/** Whole-number percentages that sum to 100 (largest share absorbs rounding). */
export function percentages(values: number[]): number[] {
  const total = values.reduce((a, b) => a + b, 0);
  if (total <= 0) return values.map(() => 0);
  const out = values.map((v) => Math.round((v / total) * 100));
  const diff = 100 - out.reduce((a, b) => a + b, 0);
  if (diff !== 0) out[out.indexOf(Math.max(...out))] += diff;
  return out;
}

export function fmtZoneTime(secs: number): string {
  const m = Math.round(secs / 60);
  if (m <= 0) return '0m';
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}` : `${m}m`;
}

/** One-line read of the easy / hard split, e.g. "78% easy, 22% at tempo or above — …". */
export function splitInsight(pcts: number[], totalSecs: number): string {
  if (totalSecs <= 0) return 'No heart-rate zone data for this period yet.';
  const easy = (pcts[0] ?? 0) + (pcts[1] ?? 0);
  const verdict =
    easy >= 78
      ? 'close to a polarized split.'
      : easy >= 70
        ? 'a little grey-zone heavy; keep tempo inside planned sessions.'
        : 'intensity is high for this block; protect your easy days.';
  return `${easy}% easy, ${100 - easy}% at tempo or above — ${verdict} ${fmtZoneTime(totalSecs)} recorded.`;
}

const SPORT_LABELS: [RegExp, string][] = [
  [/ride|bike|cycl/, 'BIKE'],
  [/run/, 'RUN'],
  [/swim/, 'SWIM'],
  [/row/, 'ROW'],
  [/strength|gym|weight/, 'GYM']
];

/** "BIKE + RUN" from the sports trained since `since`, most frequent first (max 3). */
export function sportsLabel(workouts: ZoneWorkout[], since: Date): string {
  const counts = new Map<string, number>();
  for (const w of workouts) {
    if (!w?.started_at || new Date(w.started_at).getTime() < since.getTime()) continue;
    const s = String(w.sport ?? '').toLowerCase();
    const label = SPORT_LABELS.find(([re]) => re.test(s))?.[1];
    if (label) counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k]) => k)
    .join(' + ');
}
