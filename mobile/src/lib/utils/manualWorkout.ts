/**
 * A workout the athlete logged by hand (AddActivityModal sends source: 'manual').
 * Once a device import merges into it, primary_source moves to that provider and
 * it gets provider ids, so it is no longer treated as manual.
 */
export function isManualWorkout(w: Record<string, any> | null | undefined): boolean {
  if (!w) return false;
  if (w.strava_activity_id || w.garmin_activity_id) return false;
  const primary = typeof w.primary_source === 'string' && w.primary_source ? w.primary_source : null;
  const source = primary ?? (typeof w.source === 'string' ? w.source : null);
  return source === 'manual';
}

/** Effort / RPE if the workout carries one (1–10), else null. */
export function workoutEffort(w: Record<string, any> | null | undefined): number | null {
  for (const k of ['rpe', 'perceived_exertion', 'effort']) {
    const n = Number(w?.[k]);
    if (Number.isFinite(n) && n > 0 && n <= 10) return Math.round(n * 10) / 10;
  }
  return null;
}

/** Free-text notes if the workout carries any. */
export function workoutNotes(w: Record<string, any> | null | undefined): string | null {
  for (const k of ['notes', 'description', 'note']) {
    const v = w?.[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return null;
}
