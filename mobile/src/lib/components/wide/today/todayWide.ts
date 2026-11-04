/** Pure helpers for the wide (tablet / desktop) Today layout. */
import type { Interval, Workout, WorkoutZone } from '$lib/types/training';

const ZONE_NUMBER: Record<WorkoutZone, number> = {
  Recovery: 1,
  Endurance: 2,
  Tempo: 3,
  Threshold: 4,
  VO2Max: 5,
  Anaerobic: 5
};

export const ZONE_RANGE_LABEL: Record<WorkoutZone, string> = {
  Recovery: 'Z1',
  Endurance: 'Z2',
  Tempo: 'Z3–Z4',
  Threshold: 'Z4',
  VO2Max: 'Z5',
  Anaerobic: 'Z6'
};

const SPORT_LABEL: Record<Workout['sport'], string> = {
  run: 'RUN',
  bike: 'BIKE',
  swim: 'SWIM',
  row: 'ROW',
  strength: 'STRENGTH',
  mobility: 'MOBILITY',
  other: 'WORKOUT'
};


export function zoneNumber(zone: WorkoutZone | undefined | null): number {
  return zone ? (ZONE_NUMBER[zone] ?? 0) : 0;
}

export function sportLabel(sport: Workout['sport'] | undefined): string {
  return sport ? (SPORT_LABEL[sport] ?? 'WORKOUT') : 'WORKOUT';
}

/** `pct` is the bar height as % of the chart; `zone` 0 = no target (neutral colour). */
export type ProfileBar = { grow: number; pct: number; zone: number; name: string };

/** Coggan zone for a %FTP target (same cut-offs as the Plan session sheet). */
export function zoneForFtpPct(p: number): number {
  return p < 56 ? 1 : p < 76 ? 2 : p < 91 ? 3 : p < 106 ? 4 : 5;
}

// Same geometry as the Plan session sheet's profile (96 px chart, 100% FTP line 14 px from
// the top), as percentages so the Today card draws the same shapes at any height.
const PROFILE_H = 96;
const PROFILE_TOP = 14;
const pctOfChart = (px: number) => Math.min(100, Math.round((px / PROFILE_H) * 1000) / 10);

function barFor(i: Interval): { pct: number; zone: number } {
  const ftp = typeof i.target_power_percent_ftp === 'number' && i.target_power_percent_ftp > 0 ? i.target_power_percent_ftp : null;
  const hrZone = typeof i.target_hr_zone === 'number' && i.target_hr_zone > 0 ? Math.min(5, i.target_hr_zone) : null;
  if (ftp != null) {
    return {
      pct: pctOfChart(Math.max(8, Math.round((Math.min(ftp, 130) / 100) * (PROFILE_H - PROFILE_TOP)))),
      zone: zoneForFtpPct(ftp)
    };
  }
  if (hrZone != null) return { pct: pctOfChart(14 + hrZone * 12), zone: hrZone };
  return { pct: pctOfChart(20), zone: 0 };
}

/** One block per interval, drawn exactly like the Plan session sheet: width ∝ duration,
 * height ∝ %FTP (or HR zone), coloured by zone. */
export function profileBars(w: Pick<Workout, 'structure' | 'duration_minutes' | 'primary_zone'> | null): ProfileBar[] {
  if (!w) return [];
  const steps = w.structure ?? [];
  if (steps.length > 0) {
    return steps.map((i) => ({ grow: Math.max(i.duration_minutes || 0, 1), name: i.name || '', ...barFor(i) }));
  }
  if (w.duration_minutes > 0) {
    const zone = zoneNumber(w.primary_zone);
    return [{ grow: w.duration_minutes, name: '', pct: pctOfChart(zone > 0 ? 14 + zone * 12 : 20), zone }];
  }
  return [];
}

/** "45′", "1h", "1h 25m" (design: week strip / menus). */
export function shortDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes || 0));
  if (m < 60) return `${m}′`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60 ? ` ${m % 60}m` : ''}`;
}

/** Session card stat: "85 min" or "4 h". */
export function statDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes || 0));
  return m >= 60 && m % 60 === 0 ? `${m / 60} h` : `${m} min`;
}

/** Hardest interval's %FTP (0 when the session has no power targets). */
export function workPctFtp(w: Pick<Workout, 'structure'>): number {
  return (w.structure ?? []).reduce((max, i) => Math.max(max, i.target_power_percent_ftp ?? 0), 0);
}

/** "265–279" for a bike session: the hardest step's %FTP ±2.5%, the band the Plan sheet shows. */
export function workWattRange(w: Pick<Workout, 'sport' | 'structure'>, ftp: number): string | null {
  const work = workPctFtp(w);
  if (w.sport !== 'bike' || ftp <= 0 || work <= 0) return null;
  return `${Math.round((ftp * (work - 2.5)) / 100)}–${Math.round((ftp * (work + 2.5)) / 100)}`;
}

/** Target for the session card: a watt range for bike sessions with FTP, else the zone. */
export function sessionTarget(w: Pick<Workout, 'sport' | 'structure' | 'primary_zone'>, ftp: number): string {
  const range = workWattRange(w, ftp);
  if (range) return `${range} W`;
  const label = ZONE_RANGE_LABEL[w.primary_zone];
  return label ? `${label} HR` : '—';
}

/** "412 TSS · 9H 5M PLANNED" for the week strip header. */
export function weekSummary(workouts: Pick<Workout, 'projected_tss' | 'duration_minutes'>[]): string {
  const tss = workouts.reduce((a, w) => a + (Number(w.projected_tss) || 0), 0);
  const mins = workouts.reduce((a, w) => a + (Number(w.duration_minutes) || 0), 0);
  return `${Math.round(tss)} TSS · ${Math.floor(mins / 60)}H ${Math.round(mins % 60)}M PLANNED`;
}

/**
 * Date changes for moving `source` to `targetIso`: a plain move, or a swap when the
 * target day has a session (its first session takes the source's day).
 */
export function moveChanges(
  source: Pick<Workout, 'id' | 'date'>,
  targetIso: string,
  week: Pick<Workout, 'id' | 'date' | 'completed'>[]
): { id: string; date: string }[] {
  if (!targetIso || targetIso === source.date) return [];
  const other = week.find((w) => w.date === targetIso && w.id !== source.id && !w.completed);
  const out = [{ id: source.id, date: targetIso }];
  if (other) out.push({ id: other.id, date: source.date });
  return out;
}

/** Readiness status line (same thresholds as the phone card). */
export function readinessStatus(score: number | null): { label: string; tone: 'green' | 'amber' | 'red' | 'muted' } {
  if (score === null) return { label: 'No data', tone: 'muted' };
  if (score >= 67) return { label: 'Good to train', tone: 'green' };
  if (score >= 34) return { label: 'Train as planned', tone: 'amber' };
  return { label: 'Recovery day', tone: 'red' };
}

/** A day's sessions, hardest first (the first is the day's key session). */
export function daySessions<T extends Pick<Workout, 'date' | 'projected_tss' | 'duration_minutes'>>(workouts: T[], iso: string): T[] {
  return workouts
    .filter((w) => w.date === iso)
    .sort((a, b) => (Number(b.projected_tss) || 0) - (Number(a.projected_tss) || 0) || (b.duration_minutes || 0) - (a.duration_minutes || 0));
}
