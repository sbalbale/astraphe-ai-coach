/**
 * A workout's duration in seconds, or null when it can't be known. Rows from
 * different sources carry it as `duration_seconds` or `duration_secs`; when
 * neither is set, the started_at → ended_at span is used.
 */
export function workoutDurationSecs(w: any): number | null {
  for (const key of ['duration_seconds', 'duration_secs']) {
    const raw = w?.[key];
    if (raw === null || raw === undefined || raw === '') continue;
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) return Math.floor(n);
  }
  const start = w?.started_at ? Date.parse(w.started_at) : NaN;
  const end = w?.ended_at ? Date.parse(w.ended_at) : NaN;
  if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
    return Math.floor((end - start) / 1000);
  }
  return null;
}
