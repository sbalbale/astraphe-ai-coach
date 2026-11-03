/**
 * Pure helpers for the wide (tablet / desktop) Body view: Recovery, Sleep and Strain
 * on one screen (design: WBody). Data comes from the biometrics series and workouts
 * the Body pages already load; nothing here fetches.
 */
import { format, parseISO, subDays } from 'date-fns';
import { localDay } from './localDay';
import { workoutDurationSecs } from './workoutDuration';

type Row = Record<string, any> | null | undefined;

export function finite(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function positive(v: unknown): number | null {
  const n = finite(v);
  return n !== null && n > 0 ? n : null;
}

/** "SUN → MON 2 NOV": the night that ends on the given wake day. */
export function nightWindowLabel(day: string): string {
  const wake = parseISO(day);
  if (Number.isNaN(wake.getTime())) return '';
  return `${format(subDays(wake, 1), 'EEE')} → ${format(wake, 'EEE d MMM')}`.toUpperCase();
}

const SOURCE_NAMES: Record<string, string> = {
  whoop: 'WHOOP',
  garmin: 'GARMIN',
  intervals_icu: 'INTERVALS.ICU',
  healthkit: 'APPLE HEALTH',
  apple_health: 'APPLE HEALTH',
  manual: 'MANUAL',
  strava: 'STRAVA'
};

/**
 * Devices behind a day's row ("WHOOP + GARMIN"), from `metric_sources` (field → source)
 * and `hrv_source`. Astraphe-computed scores aren't a device, so they're skipped.
 */
export function sourcesLabel(row: Row): string {
  const found: string[] = [];
  const add = (raw: unknown) => {
    if (typeof raw !== 'string') return;
    const key = raw.trim().toLowerCase();
    if (!key || key.startsWith('astraphe')) return;
    const name = SOURCE_NAMES[key] ?? key.toUpperCase();
    if (!found.includes(name)) found.push(name);
  };
  const ms = row?.metric_sources;
  if (ms && typeof ms === 'object') for (const v of Object.values(ms)) add(v);
  add(row?.hrv_source);
  return found.join(' + ');
}

/** Wide header eyebrow: "SUN → MON 2 NOV · WHOOP + GARMIN". */
export function bodyEyebrow(day: string, row: Row): string {
  return [nightWindowLabel(day), sourcesLabel(row)].filter(Boolean).join(' · ');
}

/** Mean of the `days` values before `day` (the day itself excluded), ignoring gaps and zeros. */
export function baselineBefore(series: Row[] | undefined, day: string, field: string, days = 7): number | null {
  if (!series?.length) return null;
  const end = parseISO(day);
  if (Number.isNaN(end.getTime())) return null;
  const startStr = format(subDays(end, days), 'yyyy-MM-dd');
  const vals = series
    .filter((r) => typeof r?.date === 'string' && r.date >= startStr && r.date < day)
    .map((r) => finite(r?.[field]))
    .filter((v): v is number => v !== null && v !== 0);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

/** A workout's share of daily strain: its own strain score, else TSS scaled so 150 TSS = 100. */
export function workoutStrainContribution(w: Record<string, any>): number {
  const s = positive(w?.strain_score);
  if (s !== null) return s;
  const tss = positive(w?.tss);
  return tss !== null ? (tss / 150) * 100 : 0;
}

export type DayStrain = {
  score: number;
  workouts: { workout: Record<string, any>; value: number }[];
  /** Wearable all-day strain beyond the workouts (0 when the score is workout-only). */
  activity: number;
};

/**
 * Day strain as the Strain page computes it: the wearable's strain score, or the workouts'
 * summed contribution when that is higher (or the wearable has none), capped at 100.
 */
export function dayStrain(bio: Row, workouts: Record<string, any>[]): DayStrain {
  const bioStrain = positive(bio?.strain_score);
  const parts = workouts.map((workout) => ({ workout, value: Math.round(workoutStrainContribution(workout)) }));
  const workoutScore = Math.min(100, Math.round(parts.reduce((a, p) => a + workoutStrainContribution(p.workout), 0)));
  const score =
    workouts.length > 0 || bioStrain === null
      ? Math.max(bioStrain !== null ? Math.round(bioStrain) : 0, workoutScore)
      : Math.round(bioStrain);
  const listed = parts.reduce((a, p) => a + p.value, 0);
  return { score, workouts: parts, activity: Math.max(0, score - listed) };
}

/** Workouts that started on `day` (device-local day). */
export function workoutsOn(workouts: Record<string, any>[] | undefined, day: string): Record<string, any>[] {
  return (workouts ?? []).filter((w) => localDay(w?.started_at) === day);
}

export function formatMinutes(mins: number | null | undefined): string {
  const n = finite(mins);
  if (n === null) return '--';
  const m = Math.max(0, Math.round(n));
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** "1h 25m · 148 bpm avg · 92 TSS" for a strain contributor row. */
export function workoutMeta(w: Record<string, any>): string {
  const secs = workoutDurationSecs(w);
  const parts: string[] = [];
  if (secs) parts.push(secs >= 3600 ? formatMinutes(secs / 60) : `${Math.round(secs / 60)}m`);
  const hr = positive(w?.avg_hr);
  if (hr !== null) parts.push(`${Math.round(hr)} bpm avg`);
  const tss = positive(w?.tss);
  if (tss !== null) parts.push(`${Math.round(tss)} TSS`);
  return parts.join(' · ');
}

/**
 * One sentence on why a day's recovery landed where it did, from that day's own numbers
 * against the 7 days before it. Null when there's nothing to say.
 */
export function recoveryWhy(series: Row[] | undefined, day: string): string | null {
  const row = (series ?? []).find((r) => r?.date === day);
  if (!row) return null;
  const parts: string[] = [];
  const hrv = positive(row.hrv_rmssd);
  const hrvBase = baselineBefore(series, day, 'hrv_rmssd');
  if (hrv !== null && hrvBase !== null) {
    const pct = Math.round(((hrv - hrvBase) / hrvBase) * 100);
    parts.push(Math.abs(pct) < 3 ? 'HRV at your 7-day baseline' : `HRV ${Math.abs(pct)}% ${pct > 0 ? 'above' : 'below'} your 7-day baseline`);
  }
  const rhr = positive(row.resting_hr);
  const rhrBase = baselineBefore(series, day, 'resting_hr');
  if (rhr !== null && rhrBase !== null) {
    const d = Math.round(rhr - rhrBase);
    parts.push(d === 0 ? 'resting HR steady' : `resting HR ${Math.abs(d)} bpm ${d > 0 ? 'higher' : 'lower'}`);
  }
  const sleep = positive(row.sleep_duration_min);
  if (sleep !== null) parts.push(`${formatMinutes(sleep)} asleep`);
  if (!parts.length) return null;
  const s = parts.join(', ');
  return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}

/** Round-hour ticks every `stepH` hours between two timestamps, as 0–100 % positions. */
export function hourTicks(startMs: number, endMs: number, stepH = 2, hour12 = false): { pct: number; label: string }[] {
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return [];
  const t = new Date(startMs);
  t.setMinutes(0, 0, 0);
  if (t.getTime() < startMs) t.setHours(t.getHours() + 1);
  while (t.getHours() % stepH !== 0) t.setHours(t.getHours() + 1);
  const out: { pct: number; label: string }[] = [];
  for (; t.getTime() <= endMs; t.setHours(t.getHours() + stepH)) {
    out.push({
      pct: Math.round(((t.getTime() - startMs) / (endMs - startMs)) * 1000) / 10,
      label: format(t, hour12 ? 'h a' : 'HH:mm')
    });
  }
  return out;
}
