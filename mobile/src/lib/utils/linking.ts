/**
 * Pure helpers for planned session ↔ recorded workout links (Plan sheet, Plan inspector,
 * workout picker, calendar marks). Data shapes: $lib/types/linking.ts.
 */
import { format, parseISO } from 'date-fns';
import type { LinkSource, LinkedWorkout, WorkoutCandidate } from '$lib/types/linking';

/**
 * linked   done with a recorded workout
 * mark     done by hand, no workout
 * missed   not done, day already over
 * today    not done, today
 * future   not done, later
 */
export type SessionLinkState = 'linked' | 'mark' | 'missed' | 'today' | 'future';

export function sessionLinkState(
  s: { completed?: boolean | null; completed_workout_id?: string | null; date: string },
  todayIso: string
): SessionLinkState {
  if (s.completed) return s.completed_workout_id ? 'linked' : 'mark';
  if (s.date < todayIso) return 'missed';
  return s.date === todayIso ? 'today' : 'future';
}

/** Calendar mark for a day: the first session's state (planned days keep their zone bar). */
export type DayMark = 'linked' | 'mark' | 'missed' | null;

export function dayMark(state: SessionLinkState | null): DayMark {
  return state === 'linked' || state === 'mark' || state === 'missed' ? state : null;
}

/** "45m", "1h", "1h 25". */
export function hm(minutes: number | null | undefined): string {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}h ${String(m % 60).padStart(2, '0')}` : `${h}h`;
}

/** "Mon 2 Nov" for a yyyy-MM-dd day. */
export function dayShort(iso: string): string {
  return format(parseISO(iso.slice(0, 10)), 'EEE d MMM');
}

const SPORT_BADGE: Record<string, string> = {
  bike: 'BIKE',
  run: 'RUN',
  row: 'ROW',
  swim: 'SWIM',
  strength: 'GYM',
  mobility: 'MOB'
};

/** Short uppercase badge for a sport (BIKE, RUN, ROW, GYM…). */
export function sportBadge(sport: string | null | undefined): string {
  return SPORT_BADGE[(sport ?? '').toLowerCase()] ?? 'WKT';
}

const SPORT_WORD: Record<string, string> = { bike: 'ride', run: 'run', row: 'row', swim: 'swim', strength: 'gym session', mobility: 'mobility session' };

/** "ride", "run", "gym session" for the auto-link note. */
export function sportWord(sport: string | null | undefined): string {
  return SPORT_WORD[(sport ?? '').toLowerCase()] ?? 'workout';
}

/** "Mon 2 Nov · 07:42 · 1h 25 · 92 TSS" (local time of the recording). */
export function workoutMeta(w: Pick<LinkedWorkout, 'started_at' | 'duration_seconds' | 'tss'>): string {
  const parts: string[] = [];
  const d = w.started_at ? new Date(w.started_at) : null;
  if (d && !Number.isNaN(d.getTime())) parts.push(format(d, 'EEE d MMM'), format(d, 'HH:mm'));
  parts.push(hm((w.duration_seconds || 0) / 60));
  if (w.tss != null) parts.push(`${Math.round(w.tss)} TSS`);
  return parts.join(' · ');
}

/** "TSS vs plan": % of planned with a bar width and whether it's on target (±15%). */
export function tssVsPlan(actual: number | null | undefined, planned: number | null | undefined) {
  const a = Number(actual);
  const p = Number(planned);
  if (!Number.isFinite(a) || actual == null) return { label: '—', width: 0, onTarget: false };
  if (!(p > 0)) return { label: `${Math.round(a)} TSS`, width: 100, onTarget: true };
  const pct = Math.round((a / p) * 100);
  return { label: `${pct}% of planned`, width: Math.min(100, Math.max(0, pct)), onTarget: Math.abs(a / p - 1) <= 0.15 };
}

/** "Same day as planned" / "Done 1 day late" / "Done 2 days early" from the recording's local day. */
export function dayNote(workoutStartedAt: string | null | undefined, planIso: string): string {
  if (!workoutStartedAt) return '';
  const d = new Date(workoutStartedAt);
  if (Number.isNaN(d.getTime())) return '';
  const diff = Math.round((parseISO(format(d, 'yyyy-MM-dd')).getTime() - parseISO(planIso).getTime()) / 86_400_000);
  if (diff === 0) return 'Same day as planned';
  const n = Math.abs(diff);
  return `Done ${n} day${n > 1 ? 's' : ''} ${diff > 0 ? 'late' : 'early'}`;
}

/** Why a suggested workout wasn't linked automatically (design: "Looks like a match"). */
export function suggestionWhy(fit: { auto_ok: boolean; day_offset: number; reason: string }): string {
  if (fit.auto_ok) return 'It synced after auto-matching ran.';
  if (fit.day_offset !== 0) {
    const n = Math.abs(fit.day_offset);
    return `It was done ${n} day${n > 1 ? 's' : ''} ${fit.day_offset > 0 ? 'late' : 'early'}, so it wasn’t matched automatically.`;
  }
  return `${fit.reason.charAt(0).toUpperCase()}${fit.reason.slice(1)}, so it wasn’t matched automatically.`;
}

export function linkSourceLabel(source: LinkSource | null | undefined): string {
  return source === 'auto' ? 'AUTO-MATCHED' : 'LINKED BY YOU';
}

export function unlinkText(source: LinkSource | null | undefined): string {
  return (
    'The session goes back to not done.' +
    (source === 'auto' ? ' It was auto-matched, so it won’t be matched again. You can still link it by hand.' : '')
  );
}

/** Sport filter chips for the picker: All plus the sports present. */
export function pickerSports(candidates: Pick<WorkoutCandidate, 'sport'>[]): { id: string; label: string }[] {
  const order = ['bike', 'run', 'row', 'swim', 'strength', 'mobility', 'other'];
  const label: Record<string, string> = { bike: 'Bike', run: 'Run', row: 'Row', swim: 'Swim', strength: 'Gym', mobility: 'Mobility', other: 'Other' };
  const present = order.filter((s) => candidates.some((c) => (c.sport || 'other') === s));
  return [{ id: 'all', label: 'All' }, ...present.map((s) => ({ id: s, label: label[s] }))];
}

/** Filter by search text and sport, then group: SAME DAY, WITHIN 2 DAYS. */
export function groupCandidates(
  candidates: WorkoutCandidate[],
  query: string,
  sport: string
): { name: string; rows: WorkoutCandidate[] }[] {
  const q = query.trim().toLowerCase();
  const hit = candidates.filter(
    (c) => (sport === 'all' || (c.sport || 'other') === sport) && (!q || `${c.title} ${c.sport}`.toLowerCase().includes(q))
  );
  const groups: { name: string; rows: WorkoutCandidate[] }[] = [];
  const same = hit.filter((c) => c.fit.day_offset === 0);
  const near = hit.filter((c) => c.fit.day_offset !== 0);
  if (same.length) groups.push({ name: 'SAME DAY', rows: same });
  if (near.length) groups.push({ name: 'WITHIN 2 DAYS', rows: near });
  return groups;
}

/** Tag on a picker row: LINKED HERE, or the other session it completes (ON MON 2 NOV). */
export function candidateTag(c: Pick<WorkoutCandidate, 'linked_here' | 'linked_to'>): string | null {
  if (c.linked_here) return 'LINKED HERE';
  if (c.linked_to) return `ON ${dayShort(c.linked_to.date).toUpperCase()}`;
  return null;
}

/**
 * The confirm step a pick needs: moving a link from another session and/or a different
 * sport. Null when the workout can be linked straight away.
 */
export function pendingConfirm(
  c: Pick<WorkoutCandidate, 'linked_to' | 'linked_here' | 'fit' | 'sport'>,
  planSport: string
): { kicker: string; text: string; cta: string; move: boolean } | null {
  if (c.linked_here) return null;
  const elsewhere = !!c.linked_to;
  const otherSport = !c.fit.sport_ok;
  if (!elsewhere && !otherSport) return null;
  const lines: string[] = [];
  if (elsewhere && c.linked_to) {
    lines.push(
      `This workout already completes ${c.linked_to.title || 'another session'} on ${dayShort(c.linked_to.date)}. Linking it here sets that session back to not done.`
    );
  }
  if (otherSport) {
    lines.push(`Planned ${sportWord(planSport)}, recorded ${sportWord(c.sport)}. Its TSS still counts toward the week.`);
  }
  return {
    kicker: elsewhere && otherSport ? 'MOVE LINK · DIFFERENT SPORT' : elsewhere ? 'MOVE LINK' : 'DIFFERENT SPORT',
    text: lines.join(' '),
    cta: elsewhere ? 'Move link here' : 'Link anyway',
    move: elsewhere
  };
}
