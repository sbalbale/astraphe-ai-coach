/**
 * Helpers for the planned-session panel on a recorded workout (design: PWorkoutLink):
 * labels and the session picker (the planned-vs-actual chart lives in planVsActual.ts).
 */
import { format, parseISO } from 'date-fns';
import type { PlanCandidate, PlanSummary } from '$lib/types/linking';

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
