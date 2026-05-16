export function formatPace(s: number | null): string {
  if (s == null) return '—';
  const r = Math.round(s);
  const m = Math.floor(r / 60);
  const sec = r % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

export function formatDist(m: number | null): string {
  if (m == null) return '—';
  return `${Math.round(m)}m`;
}

export function formatHR(bpm: number | null): string {
  if (bpm == null) return '—';
  return String(Math.round(bpm));
}
