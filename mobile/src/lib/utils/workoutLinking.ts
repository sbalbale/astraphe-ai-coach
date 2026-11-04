/**
 * Helpers for the planned-session panel on a recorded workout (design: PWorkoutLink):
 * labels, the planned-vs-actual table, the planned-blocks overlay and the session picker.
 */
import { format, parseISO } from 'date-fns';
import type { Interval } from '$lib/types/training';
import type { PlanCandidate, PlanSummary } from '$lib/types/linking';
import { zoneForFtpPct } from '$lib/components/wide/today/todayWide';

/** "45′", "1h", "1h 25". */
export function hm(minutes: number): string {
  const m = Math.max(0, Math.round(minutes || 0));
  if (m < 60) return `${m}′`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}h ${String(m % 60).padStart(2, '0')}` : `${h}h`;
}

/** "Tue 3 Nov". */
export function dayShort(iso: string): string {
  try {
    return format(parseISO(iso.slice(0, 10)), 'EEE d MMM');
  } catch {
    return iso;
  }
}

/** "Tue 3 Nov · 1h 30 · 105 TSS" for a planned session. */
export function sessionMeta(p: Pick<PlanSummary, 'date' | 'duration_minutes' | 'projected_tss'>): string {
  return [dayShort(p.date), p.duration_minutes ? hm(p.duration_minutes) : null, p.projected_tss ? `${p.projected_tss} TSS` : null]
    .filter(Boolean)
    .join(' · ');
}

export function unlinkedText(hasSuggestion: boolean): string {
  return hasSuggestion
    ? 'This workout isn’t linked to a session yet.'
    : 'This workout wasn’t in the plan. It still counts toward your weekly load.';
}

export function unlinkConfirmText(p: Pick<PlanSummary, 'title' | 'date'>, source: string | null | undefined): string {
  return `${p.title} on ${dayShort(p.date)} goes back to not done.${source === 'auto' ? ' It won’t be auto-matched again.' : ''}`;
}

export type CmpTone = 'good' | 'warn' | 'neutral';
export type CmpRow = { k: string; p: string; a: string; tone: CmpTone };

/** Seconds at or above `threshold` in a stream sampled at `time` (or every `step` s). */
export function secondsAtOrAbove(values: number[] | undefined, threshold: number, time?: number[], step = 1): number {
  if (!values?.length || threshold <= 0) return 0;
  let s = 0;
  for (let i = 0; i < values.length; i++) {
    if (!(values[i] >= threshold)) continue;
    const dt = time && i + 1 < time.length ? Math.min(Math.max(time[i + 1] - time[i], 0), 30) : step;
    s += dt;
  }
  return Math.round(s);
}

/**
 * Planned vs actual rows. Duration and TSS always (when known); time at threshold (≥ 91%
 * FTP) only when the plan has power targets and a power stream + FTP exist.
 */
export function comparisonRows(
  plan: { duration_minutes: number; projected_tss: number; structure?: Interval[] },
  actual: { duration_seconds: number; tss: number | null },
  power?: { watts?: number[]; time?: number[]; step?: number; ftp?: number }
): CmpRow[] {
  const rows: CmpRow[] = [];
  const actualMin = (actual.duration_seconds || 0) / 60;
  if (plan.duration_minutes > 0 && actualMin > 0) {
    const ok = Math.abs(actualMin / plan.duration_minutes - 1) < 0.1;
    rows.push({ k: 'Duration', p: hm(plan.duration_minutes), a: hm(actualMin), tone: ok ? 'good' : 'warn' });
  }
  if (plan.projected_tss > 0 && actual.tss != null) {
    const pct = Math.round((actual.tss / plan.projected_tss) * 100);
    rows.push({ k: 'TSS', p: String(plan.projected_tss), a: `${Math.round(actual.tss)} · ${pct}%`, tone: Math.abs(pct - 100) <= 15 ? 'good' : 'warn' });
  }
  const hardPlanned = (plan.structure ?? []).reduce(
    (s, i) => s + ((i.target_power_percent_ftp ?? 0) >= 91 ? i.duration_minutes || 0 : 0),
    0
  );
  if (hardPlanned > 0 && power?.watts?.length && power.ftp) {
    const sec = secondsAtOrAbove(power.watts, power.ftp * 0.91, power.time, power.step ?? 1);
    const ratio = sec / 60 / hardPlanned;
    rows.push({ k: 'Time at threshold', p: hm(hardPlanned), a: hm(sec / 60), tone: ratio >= 0.85 && ratio <= 1.2 ? 'good' : 'warn' });
  }
  return rows;
}

export type Block = { x: number; y: number; w: number; h: number; color: string };

/** Planned interval blocks across a `width` × `height` chart; `spanMin` is the x-axis length. */
export function plannedBlocks(structure: Interval[], spanMin: number, width: number, height: number, maxPct = 130): Block[] {
  const out: Block[] = [];
  let t = 0;
  for (const i of structure) {
    const min = Math.max(0, i.duration_minutes || 0);
    if (!min) continue;
    const pct = i.target_power_percent_ftp ?? (i.target_hr_zone ? [0, 55, 70, 85, 100, 115][Math.min(5, i.target_hr_zone)] : 50);
    const zone = i.target_power_percent_ftp ? zoneForFtpPct(i.target_power_percent_ftp) : i.target_hr_zone ?? 0;
    const h = Math.max(4, Math.min(1, pct / maxPct) * (height - 4));
    out.push({
      x: (t / spanMin) * width,
      y: height - h,
      w: Math.max(1, (min / spanMin) * width - 1),
      h,
      color: zone > 0 ? `var(--zone-${zone})` : 'var(--text2)'
    });
    t += min;
  }
  return out;
}

/**
 * Polyline points for a stream (downsampled to ~`buckets` averages) over `spanMin` minutes;
 * values are scaled so `maxValue` is the top of the chart.
 */
export function traceLine(
  values: number[] | undefined,
  time: number[] | undefined,
  step: number,
  spanMin: number,
  width: number,
  height: number,
  maxValue: number,
  buckets = 120
): string {
  if (!values?.length || maxValue <= 0 || spanMin <= 0) return '';
  const n = values.length;
  const per = Math.max(1, Math.ceil(n / buckets));
  const pts: string[] = [];
  for (let i = 0; i < n; i += per) {
    let sum = 0;
    let cnt = 0;
    for (let j = i; j < Math.min(n, i + per); j++) {
      if (Number.isFinite(values[j])) {
        sum += values[j];
        cnt++;
      }
    }
    if (!cnt) continue;
    const mid = Math.min(n - 1, i + Math.floor(per / 2));
    const sec = time?.[mid] ?? mid * step;
    const x = Math.min(width, (sec / 60 / spanMin) * width);
    const y = height - Math.min(1, sum / cnt / maxValue) * (height - 4);
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return pts.join(' ');
}

export type PickerTag = { label: string; kind: 'here' | 'other' | 'done' | 'sport' } | null;

/** Tag on a picker row (design: LINKED HERE / LINKED TO OTHER / DONE · NO FILE / DIFFERENT SPORT). */
export function pickerTag(c: PlanCandidate): PickerTag {
  if (c.linked_here) return { label: 'LINKED HERE', kind: 'here' };
  if (c.has_other_workout) return { label: 'LINKED', kind: 'other' };
  if (c.completed) return { label: 'DONE · NO FILE', kind: 'done' };
  if (!c.fit.sport_ok) return { label: 'DIFFERENT SPORT', kind: 'sport' };
  return null;
}

export type Pending = { kicker: string; text: string; cta: string };

/**
 * Confirm step before linking to a session that's already completed by another recording,
 * or is a different sport. Null when the link can go straight through.
 */
export function pendingFor(c: PlanCandidate, workoutSport: string): Pending | null {
  const parts: string[] = [];
  let kicker = '';
  let cta = 'Link anyway';
  if (c.has_other_workout) {
    kicker = 'REPLACE LINK';
    cta = 'Replace';
    parts.push(`${c.title} is already completed by another recorded workout. That one will be unlinked.`);
  }
  if (!c.fit.sport_ok) {
    kicker = kicker || 'DIFFERENT SPORT';
    parts.push(`Planned ${c.sport.toLowerCase()}, recorded ${workoutSport.toLowerCase()}. Linking still marks the session done.`);
  }
  return parts.length ? { kicker, text: parts.join(' '), cta } : null;
}

/** Picker rows filtered by a search query (title or date). */
export function filterSessions(rows: PlanCandidate[], query: string): PlanCandidate[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((r) => `${r.title} ${dayShort(r.date)} ${r.sport}`.toLowerCase().includes(q));
}
