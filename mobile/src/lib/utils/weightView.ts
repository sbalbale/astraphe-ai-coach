/**
 * Weight screen (design: WeightView). Pure helpers over the year of weigh-ins from
 * GET /v1/weight. Days are offsets from the athlete's today (0 = today, -1 = yesterday).
 */
import { differenceInCalendarDays, parseISO } from 'date-fns';
import type { WeighIn } from '$lib/types/weight';

export const KG_PER_LB = 0.45359237;
export type WeightUnit = 'kg' | 'lb';
export type Metric = 'weight' | 'fat';
export const RANGES = [
  { days: 30, label: '30D' },
  { days: 90, label: '90D' },
  { days: 180, label: '6M' },
  { days: 365, label: '1Y' }
] as const;

/** Smoothing per day of weigh-ins. Gaps compound it (see `smooth`). */
const ALPHA = 0.1;

export const toUnit = (kg: number, u: WeightUnit) => (u === 'kg' ? kg : kg / KG_PER_LB);
export const fromUnit = (v: number, u: WeightUnit) => (u === 'kg' ? v : v * KG_PER_LB);
export const r1 = (x: number) => (Math.round(x * 10) / 10).toFixed(1);

export type Entry = WeighIn & { o: number };

export function withOffsets(entries: WeighIn[], today: string): Entry[] {
  const t = parseISO(today);
  return entries
    .map((e) => ({ ...e, o: differenceInCalendarDays(parseISO(e.date), t) }))
    .filter((e) => e.o <= 0)
    .sort((a, b) => a.o - b.o || a.measured_at.localeCompare(b.measured_at));
}

/**
 * Daily trend (value per day offset, null before the first reading), an exponential
 * moving average of each day's mean. With daily weigh-ins it's the plain EWMA (alpha
 * 0.1); a gap of n days counts as n steps, so a reading after weeks away moves the
 * trend as far as a run of daily readings at that value would have, instead of 10%.
 * Days between readings are interpolated (a flat line then a cliff read as a sudden
 * change on the reading day); after the last reading the trend holds until today.
 */
export function smooth(points: { o: number; v: number }[], from: number): Map<number, number | null> {
  const byDay = new Map<number, number[]>();
  for (const p of points) byDay.set(p.o, [...(byDay.get(p.o) ?? []), p.v]);
  const days = [...byDay.keys()].sort((a, b) => a - b);
  const at = new Map<number, number>();
  let t: number | null = null;
  let last = 0;
  for (const o of days) {
    const v = byDay.get(o)!;
    const m = v.reduce((s, x) => s + x, 0) / v.length;
    t = t === null ? m : t + (m - t) * (1 - Math.pow(1 - ALPHA, Math.max(1, o - last)));
    at.set(o, t);
    last = o;
  }
  const out = new Map<number, number | null>();
  const start = Math.min(from, ...days);
  let i = 0;
  for (let o = start; o <= 0; o++) {
    while (i < days.length && days[i] < o) i++;
    if (i < days.length && days[i] === o) out.set(o, at.get(o)!);
    else if (i === 0) out.set(o, null);
    else if (i >= days.length) out.set(o, at.get(days[days.length - 1])!);
    else {
      const a = days[i - 1], b = days[i];
      const va = at.get(a)!, vb = at.get(b)!;
      out.set(o, va + ((vb - va) * (o - a)) / (b - a));
    }
  }
  return out;
}

/** Trend change per week over the last 4 weeks (kg), when 2+ weigh-ins fall in them. */
export function ratePerWeek(entries: Entry[], trend: Map<number, number | null>): number | null {
  const recent = entries.filter((e) => e.o >= -28);
  const then = trend.get(-28);
  const now = trend.get(0);
  if (recent.length < 2 || then == null || now == null) return null;
  return (now - then) / 4;
}

/** Days until the trend reaches `goal` at `perWeek` (kg/wk), or 0 if it isn't heading there. */
export function daysToGoal(now: number, goal: number | null, perWeek: number | null): number {
  if (goal == null || perWeek == null || Math.abs(perWeek) < 0.02) return 0;
  const gap = goal - now;
  if (Math.abs(gap) < 0.05 || Math.sign(gap) !== Math.sign(perWeek)) return 0;
  return Math.min(120, Math.ceil(Math.abs(gap) / (Math.abs(perWeek) / 7)));
}

export function gridValues(lo: number, hi: number, step: number): number[] {
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 10) / 10);
  // Keep the axis readable over a wide spread.
  return out.length > 6 ? gridValues(lo, hi, step * 2) : out;
}

export function tickOffsets(range: number): number[] {
  const step = range <= 30 ? 7 : range <= 90 ? 30 : range <= 180 ? 60 : 91;
  const out: number[] = [];
  for (let o = 0; o >= -range; o -= step) out.push(o);
  return out;
}

const SOURCE_LABELS: Record<string, string> = {
  manual: 'Manual',
  garmin: 'Garmin',
  whoop: 'WHOOP',
  healthkit: 'Apple Health',
  intervals_icu: 'Intervals.icu'
};
export const sourceLabel = (s: string) => SOURCE_LABELS[s] ?? s;

/** The coach's one-liner on the 4-week rate (kg/wk) and body weight (kg). */
export function coachLine(perWeek: number | null, nowKg: number | null, u: WeightUnit, wkg: number | null): string {
  if (perWeek == null || nowKg == null) {
    return 'Weigh in a few times a week, same time of day, and a trend shows here. Single readings swing 1–2 ' + u + ' with water.';
  }
  const pct = (Math.abs(perWeek) / nowKg) * 100;
  const amt = `${r1(toUnit(Math.abs(perWeek), u))} ${u}`;
  if (perWeek < 0 && pct > 1) {
    return `You're losing ${amt} a week, more than 1% of body weight. That's fast while training — eat more on long or hard days or performance will dip.`;
  }
  if (perWeek < -0.02) {
    return `Down ${amt} a week, about ${pct.toFixed(1)}% of body weight. That's a safe rate while training${wkg ? `, and power-to-weight is up to ${wkg.toFixed(2)} W/kg` : ''}. Keep carbs high on long days.`;
  }
  if (perWeek > 0.02 && pct > 0.5) {
    return `Up ${amt} a week. If you're not trying to gain, check recovery and portion sizes on rest days.`;
  }
  return `Weight is steady. Day-to-day swings of 1–2 ${u} are mostly water — the trend line is what counts.`;
}
