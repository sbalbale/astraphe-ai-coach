/**
 * Workout block lengths in minutes and seconds. Blocks can be fractional minutes
 * (8 × 1:30 → 1.5), which must never be rounded to whole minutes.
 *
 *   15   → "15′"      1.5 → "1′30″"     0.75 → "0′45″"     90 → "1h30"
 */
export function formatStepDuration(minutes: number): string {
  const secs = Math.max(0, Math.round((Number(minutes) || 0) * 60));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  if (s === 0) {
    if (m < 60) return `${m}′`;
    const rest = m % 60;
    return `${Math.floor(m / 60)}h${rest ? String(rest).padStart(2, '0') : ''}`;
  }
  return `${m}′${String(s).padStart(2, '0')}″`;
}

/** Clock style for step start/end times: 1.5 → "01:30", 75.25 → "75:15". */
export function formatStepClock(minutes: number): string {
  const secs = Math.max(0, Math.round((Number(minutes) || 0) * 60));
  return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
}
