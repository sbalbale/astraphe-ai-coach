/** Pure helpers for the wide Coach screen (conversation list + "What I can see" pane). */
import { addDays, differenceInCalendarDays, format, startOfWeek } from 'date-fns';
import { WEEK_STARTS_ON } from '$lib/utils/week';

/** "Today", a weekday within the last 6 days, else "27 Oct" (or "27 Oct 2025" in another year). */
export function conversationWhen(iso: string | undefined | null, now: Date = new Date()): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const days = differenceInCalendarDays(now, d);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return format(d, 'EEE');
  return format(d, d.getFullYear() === now.getFullYear() ? 'd MMM' : 'd MMM yyyy');
}

/** Conversations whose title contains `query` (case-insensitive); untitled ones count as "New chat". */
export function filterConversations<T extends { title?: string | null }>(rows: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((c) => (c.title || 'New chat').toLowerCase().includes(q));
}

/** Monday–Sunday ISO dates of the week containing `now`. */
export function weekRange(now: Date = new Date()): { start: string; end: string } {
  const start = startOfWeek(now, { weekStartsOn: WEEK_STARTS_ON });
  return { start: format(start, 'yyyy-MM-dd'), end: format(addDays(start, 6), 'yyyy-MM-dd') };
}

type CompletedWorkout = { started_at?: string | null; tss?: number | null };
type PlannedWorkout = { date?: string; projected_tss?: number | null };

/**
 * This week's load: TSS done (completed workouts started this week) and TSS planned
 * (planned sessions dated this week). null when there is neither.
 */
export function weekLoad(
  completed: CompletedWorkout[] | null | undefined,
  planned: PlannedWorkout[] | null | undefined,
  range: { start: string; end: string }
): { done: number; planned: number; pct: number } | null {
  const inWeek = (iso: string) => iso >= range.start && iso <= range.end;
  const done = (completed ?? []).reduce((sum, w) => {
    const day = w.started_at ? format(new Date(w.started_at), 'yyyy-MM-dd') : '';
    const tss = Number(w.tss);
    return day && inWeek(day) && Number.isFinite(tss) && tss > 0 ? sum + tss : sum;
  }, 0);
  const plannedTss = (planned ?? []).reduce((sum, w) => {
    const tss = Number(w.projected_tss);
    return w.date && inWeek(w.date) && Number.isFinite(tss) && tss > 0 ? sum + tss : sum;
  }, 0);
  if (done <= 0 && plannedTss <= 0) return null;
  const pct = plannedTss > 0 ? Math.min(100, Math.round((done / plannedTss) * 100)) : 100;
  return { done: Math.round(done), planned: Math.round(plannedTss), pct };
}

/** "Garmin · WHOOP" from sync-status integrations; '' when nothing is connected. */
export function connectedSourcesLabel(integrations: Record<string, { connected?: boolean } | undefined> | null | undefined): string {
  const NAMES: [string, string][] = [
    ['garmin', 'Garmin'],
    ['whoop', 'WHOOP'],
    ['strava', 'Strava'],
    ['intervals_icu', 'Intervals.icu'],
    ['healthkit', 'Apple Health']
  ];
  return NAMES.filter(([k]) => integrations?.[k]?.connected).map(([, n]) => n).join(' · ');
}

/** "85′ · BIKE · 92 TSS" for a planned session. */
export function sessionMeta(w: { duration_minutes?: number | null; sport?: string | null; projected_tss?: number | null }): string {
  const parts: string[] = [];
  const min = Number(w.duration_minutes);
  if (Number.isFinite(min) && min > 0) parts.push(`${Math.round(min)}′`);
  if (w.sport) parts.push(w.sport.toUpperCase());
  const tss = Number(w.projected_tss);
  if (Number.isFinite(tss) && tss > 0) parts.push(`${Math.round(tss)} TSS`);
  return parts.join(' · ');
}
