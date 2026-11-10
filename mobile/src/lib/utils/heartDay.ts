/**
 * Full-day heart rate (design: HeartDay). Pure helpers: the API's samples become a
 * per-minute array over the athlete's local day, which the chart, stats, zones and
 * day timeline all read with minute ranges [a, b).
 */
import type { HeartRateDay } from '$lib/types/heartRate';

export type SpanKind = 'sleep' | 'workout' | 'detected';
export type DaySpan = { kind: SpanKind; a: number; b: number; title: string; workoutId?: string };
export type ZoneDef = { zone: number; min: number; max: number };

export const MIN_MS = 60_000;
/** A sample stands for at most this long; a longer hole is a gap (watch off). */
const MAX_FILL_MIN = 5;

export type DayModel = {
  /** Minutes in the local day (1440; 1380 / 1500 on clock-change days). */
  len: number;
  /** bpm per minute of the day, null where there's no reading. */
  hr: (number | null)[];
  spans: DaySpan[];
  dayStartMs: number;
};

function minuteOf(iso: string | null | undefined, dayStartMs: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? (t - dayStartMs) / MIN_MS : null;
}

export function buildDayModel(day: HeartRateDay): DayModel {
  const dayStartMs = Date.parse(day.day_start);
  const len = Math.max(1, Math.round((Date.parse(day.day_end) - dayStartMs) / MIN_MS)) || 1440;
  const hr: (number | null)[] = new Array(len).fill(null);
  const step = Math.min(MAX_FILL_MIN, Math.max(1, Math.round((day.interval_sec ?? 60) / 60)));
  const pts = day.samples
    .map((s) => ({ m: minuteOf(s.t, dayStartMs), bpm: s.bpm }))
    .filter((p): p is { m: number; bpm: number } => p.m !== null && p.m >= 0 && p.m < len);
  for (let i = 0; i < pts.length; i++) {
    const m0 = Math.floor(pts[i].m);
    const next = i + 1 < pts.length ? Math.floor(pts[i + 1].m) : m0 + step;
    const m1 = Math.min(len, m0 + Math.min(MAX_FILL_MIN, Math.max(1, next - m0)));
    for (let m = m0; m < m1; m++) hr[m] = pts[i].bpm;
  }

  // Whole minutes: everything downstream indexes the per-minute array with span bounds.
  const clip = (a: number | null, b: number | null) =>
    a === null || b === null ? null : ([Math.max(0, Math.round(a)), Math.min(len, Math.round(b))] as const);
  const spans: DaySpan[] = [];
  for (const s of day.sleep ?? []) {
    const c = clip(minuteOf(s.started_at, dayStartMs), minuteOf(s.ended_at, dayStartMs));
    if (c && c[1] > c[0]) spans.push({ kind: 'sleep', a: c[0], b: c[1], title: s.is_nap ? 'Nap' : 'Sleep' });
  }
  for (const w of day.workouts ?? []) {
    const a = minuteOf(w.started_at, dayStartMs);
    const end = w.ended_at ?? (w.duration_seconds ? new Date(Date.parse(w.started_at) + w.duration_seconds * 1000).toISOString() : null);
    const c = clip(a, minuteOf(end, dayStartMs));
    if (!c || c[1] <= c[0]) continue;
    spans.push({
      kind: w.detected ? 'detected' : 'workout',
      a: c[0],
      b: c[1],
      title: (w.title || '').trim() || (w.detected ? 'Detected activity' : 'Workout'),
      workoutId: w.id
    });
  }
  spans.sort((x, y) => x.a - y.a);
  return { len, hr, spans, dayStartMs };
}

export type RangeStats = { avg: number | null; max: number | null; min: number | null; n: number };

export function rangeStats(hr: (number | null)[], a: number, b: number): RangeStats {
  let sum = 0, n = 0, max = -Infinity, min = Infinity;
  for (let m = Math.max(0, Math.floor(a)); m < Math.min(hr.length, Math.ceil(b)); m++) {
    const v = hr[m];
    if (v === null || v === undefined) continue;
    sum += v; n++;
    if (v > max) max = v;
    if (v < min) min = v;
  }
  return n ? { avg: Math.round(sum / n), max, min, n } : { avg: null, max: null, min: null, n: 0 };
}

/** SVG path over a 1000 × 200 viewBox, bucketed to ~360 points, broken at gaps. */
export function chartPath(
  hr: (number | null)[],
  a: number,
  b: number,
  y: (bpm: number) => number
): string {
  const span = b - a;
  const step = Math.max(1, Math.floor(span / 360));
  const x = (m: number) => ((m - a) / span) * 1000;
  let d = '';
  let pen = false;
  for (let m = Math.floor(a); m < b; m += step) {
    let sum = 0, n = 0;
    for (let k = Math.max(0, m); k < Math.min(b, m + step); k++) {
      const v = hr[k];
      if (v !== null && v !== undefined) { sum += v; n++; }
    }
    if (!n) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${x(m + step / 2).toFixed(1)} ${y(sum / n).toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** Y in the 200-high viewBox for 35–185 bpm (clamped), like the design. */
export const chartY = (bpm: number, lo = 35, hi = 185) => 200 - ((Math.max(lo, Math.min(hi, bpm)) - lo) / (hi - lo)) * 200;

/** Axis range covering the day's readings with some room (never narrower than the design's). */
export function chartRange(hr: (number | null)[]): { lo: number; hi: number } {
  let max = 0;
  for (const v of hr) if (v !== null && v > max) max = v;
  return { lo: 35, hi: Math.max(185, Math.ceil((max + 10) / 10) * 10) };
}

/** `compact` (phone width) halves the label count so "HH:MM" labels don't run together. */
export function tickMinutes(a: number, b: number, compact = false): number[] {
  const span = b - a;
  const iv = (span > 720 ? 180 : span > 300 ? 60 : span > 120 ? 30 : 15) * (compact && span > 120 ? 2 : 1);
  const out: number[] = [];
  for (let m = Math.ceil(a / iv) * iv; m <= b; m += iv) out.push(m);
  return out;
}

export function clockAt(dayStartMs: number, m: number): string {
  const d = new Date(dayStartMs + Math.round(m) * MIN_MS);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function formatMins(n: number): string {
  const r = Math.round(n);
  return r >= 60 ? `${Math.floor(r / 60)}h ${String(r % 60).padStart(2, '0')}` : `${r}m`;
}

export function zoneOf(bpm: number, zones: ZoneDef[]): number | null {
  for (let i = zones.length - 1; i >= 0; i--) if (bpm >= zones[i].min) return zones[i].zone;
  return zones.length ? zones[0].zone : null;
}

/**
 * Minutes per zone in [a, b). Every profile zone model starts Z1 at 0 bpm, so minutes
 * under `restBelow` count as rest rather than Z1.
 */
export function zoneMinutes(hr: (number | null)[], a: number, b: number, zones: ZoneDef[], restBelow: number): Record<number, number> {
  const out: Record<number, number> = {};
  for (const z of zones) out[z.zone] = 0;
  for (let m = Math.max(0, Math.floor(a)); m < Math.min(hr.length, Math.ceil(b)); m++) {
    const v = hr[m];
    if (v === null || v === undefined || v < restBelow) continue;
    const z = zoneOf(v, zones);
    if (z !== null) out[z] += 1;
  }
  return out;
}

/** Floor of the "training" zones: half of max HR (the common bottom of Z1). */
export function restFloor(maxHr: number | null | undefined): number {
  return maxHr && maxHr > 0 ? Math.round(maxHr * 0.5) : 100;
}

/** Zoom presets: whole day, overnight, each workout or detection (±15 min). */
export function zoomPresets(model: DayModel): { label: string; r: [number, number] | null }[] {
  const { len, spans } = model;
  const pad = (s: DaySpan): [number, number] => [Math.max(0, s.a - 15), Math.min(len, s.b + 15)];
  const out: { label: string; r: [number, number] | null }[] = [{ label: 'Whole day', r: null }];
  const night = spans.find((s) => s.kind === 'sleep' && s.a < 12 * 60);
  if (night) out.push({ label: 'Overnight', r: [0, Math.min(len, night.b + 30)] });
  for (const s of spans) {
    if (s.kind === 'sleep') continue;
    // Detections share one title; their start time tells them apart.
    const label = s.kind === 'detected' ? `Detected · ${clockAt(model.dayStartMs, s.a)}` : s.title;
    out.push({ label, r: pad(s) });
  }
  return out;
}

export function sameRange(x: [number, number] | null, y: [number, number] | null): boolean {
  return (!x && !y) || (!!x && !!y && x[0] === y[0] && x[1] === y[1]);
}

/** Resting-HR change vs the trailing 30-day average (excluding the day itself). */
export function restingVsAverage(history: { date: string; resting_hr: number }[], day: string): number | null {
  const today = history.find((h) => h.date === day)?.resting_hr;
  const prior = history.filter((h) => h.date < day).map((h) => h.resting_hr);
  if (!today || prior.length < 3) return null;
  return Math.round(today - prior.reduce((s, v) => s + v, 0) / prior.length);
}
