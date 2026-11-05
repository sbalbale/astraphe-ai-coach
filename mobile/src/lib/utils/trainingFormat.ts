/**
 * Display helpers for the Training log (phone list/detail and the wide master–detail).
 * Workouts are API rows (`/v1/workouts`), so fields are read defensively.
 */
import { format, addDays } from 'date-fns';
import type { Units as MeasurementUnits } from '$lib/utils/units';

type W = Record<string, any> | null | undefined;

export function getWorkoutLabel(type: string | null | undefined): string {
  const t = type?.toLowerCase();
  if (t === 'strength_training' || t === 'strength' || t === 'gym') return 'Strength';
  if (t === 'mobility') return 'Mobility';
  if (t === 'other') return 'Other';
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Workout';
}

export function getDurationSecs(w: W): number {
  const direct = w?.duration_secs ?? w?.duration_seconds;
  if (direct != null && Number.isFinite(Number(direct))) return Math.max(0, Math.floor(Number(direct)));
  const start = w?.started_at ? new Date(w.started_at) : null;
  const end = w?.ended_at ? new Date(w.ended_at) : null;
  if (!start || !end) return 0;
  const ms = end.getTime() - start.getTime();
  if (!Number.isFinite(ms)) return 0;
  return Math.max(0, Math.floor(ms / 1000));
}

export function formatAvgPower(w: W): string {
  const raw = w?.avg_power_w ?? w?.average_watts;
  if (raw == null) return '--';
  const watts = Number(raw);
  return Number.isFinite(watts) ? String(Math.round(watts)) : '--';
}

export function formatMMSS(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Z1–Z5 percentages (null where missing). */
export function getHrZonePcts(w: W): Array<number | null> {
  return [w?.hr_zone_1_pct, w?.hr_zone_2_pct, w?.hr_zone_3_pct, w?.hr_zone_4_pct, w?.hr_zone_5_pct].map((v) =>
    v == null ? null : Number(v)
  );
}

/** Display order Z5 (top) → Z1 (bottom). */
export function getHrZonePctsTopDown(w: W): Array<number | null> {
  return getHrZonePcts(w).slice().reverse();
}

export function hasAnyHrZone(w: W): boolean {
  return getHrZonePcts(w).some((v) => v != null);
}

const SPORT_GLYPHS: Record<string, string> = {
  bike: 'BIKE', cycling: 'BIKE', ride: 'BIKE', run: 'RUN', running: 'RUN', swim: 'SWIM', swimming: 'SWIM',
  strength: 'GYM', strength_training: 'GYM', gym: 'GYM', row: 'ROW', rowing: 'ROW', mobility: 'MOB'
};

export function sportGlyph(sport: string | null | undefined): string {
  return SPORT_GLYPHS[String(sport ?? '').toLowerCase()] ?? 'OTHER';
}

/** "1h 05m" / "42m". */
export function formatHoursMinutes(secs: number): string {
  // Round to whole minutes first, so 1h 59m 30s reads "2h 00m", not "1h 60m".
  const total = Math.round(Math.max(0, Number(secs) || 0) / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

/** List row meta: "Mon 2 Nov · 1h 25m · 44.2 km · 244 W NP". */
export function activityMeta(w: W, units: MeasurementUnits): string {
  const parts: string[] = [];
  const d = w?.started_at ? new Date(w.started_at) : null;
  if (d && !Number.isNaN(d.getTime())) parts.push(format(d, 'EEE d MMM'));
  const secs = getDurationSecs(w);
  if (secs > 0) parts.push(formatHoursMinutes(secs));
  const meters = Number(w?.distance_m) || 0;
  if (meters > 0) parts.push(units === 'imperial' ? `${(meters / 1609.344).toFixed(1)} mi` : `${(meters / 1000).toFixed(1)} km`);
  const np = Number(w?.norm_power_w) || 0;
  if (np > 0) parts.push(`${np} W NP`);
  return parts.join(' · ');
}

/** Positive rounded number, else null (TSS / strain on rows). */
export function positiveRounded(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

/** Wide list eyebrow: "WEEK 45 · THIS WEEK" / "WEEK 44". */
export function weekEyebrow(weekStart: Date, isCurrentWeek: boolean): string {
  // The week's dates, not a week number: "1 – 7 NOV · THIS WEEK", "25 OCT – 31 OCT".
  const end = addDays(weekStart, 6);
  const range =
    format(weekStart, 'MMM') === format(end, 'MMM')
      ? `${format(weekStart, 'd')} – ${format(end, 'd MMM')}`
      : `${format(weekStart, 'd MMM')} – ${format(end, 'd MMM')}`;
  return `${range.toUpperCase()}${isCurrentWeek ? ' · THIS WEEK' : ''}`;
}

// --- Splits table cells (units live in the column header, not the cell) ---

export function splitTime(secs: number): string {
  const t = Math.max(0, Math.round(Number(secs) || 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const ss = String(t % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

export function splitDistance(meters: number, units: MeasurementUnits): string {
  const m = Number(meters) || 0;
  if (m <= 0) return '—';
  return (units === 'imperial' ? m / 1609.344 : m / 1000).toFixed(m < 1000 ? 2 : 1);
}

export function splitPace(secs: number | null): string {
  const p = Number(secs);
  if (!Number.isFinite(p) || p <= 0) return '—';
  const s = Math.round(p); // whole seconds first: 299.6 s is "5:00", not "4:60"
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function splitSpeed(r: any, units: MeasurementUnits): string {
  const v =
    Number(r?.average_speed) > 0
      ? Number(r.average_speed)
      : Number(r?.distance) > 0 && Number(r?.elapsed_time) > 0
        ? Number(r.distance) / Number(r.elapsed_time)
        : 0;
  if (v <= 0) return '—';
  return (units === 'imperial' ? v * 2.23694 : v * 3.6).toFixed(1);
}

type StreamsLike = { time_series?: Record<string, unknown[] | undefined>; resolution_seconds?: number } | null | undefined;

/** Stored stream channels, e.g. ["Heart rate", "Power", "GPS"]. */
export function streamChannels(streams: StreamsLike): string[] {
  const ts = streams?.time_series ?? {};
  const has = (k: string) => Array.isArray(ts[k]) && (ts[k] as unknown[]).length > 1;
  const out: string[] = [];
  if (has('heartrate')) out.push('Heart rate');
  if (has('watts')) out.push('Power');
  if (has('cadence')) out.push('Cadence');
  if (has('velocity_smooth')) out.push('Speed');
  if (has('altitude')) out.push('Elevation');
  if (has('latlng')) out.push('GPS');
  return out;
}

/** "1 s" / "5 s" sample interval, or null when unknown. */
export function sampleRateLabel(streams: StreamsLike): string | null {
  const r = Number(streams?.resolution_seconds);
  return Number.isFinite(r) && r > 0 ? `${r < 1 ? r.toFixed(1) : Math.round(r)} s` : null;
}
