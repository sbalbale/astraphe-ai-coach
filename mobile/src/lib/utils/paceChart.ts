import * as d3 from 'd3';
import { normalizeUnits, type Units } from '$lib/utils/units';

const PACE_QUANTILE_LO = 0.02;
const PACE_QUANTILE_HI = 0.98;
const METERS_PER_MILE = 1609.344;
const KM_PER_MILE = METERS_PER_MILE / 1000;
const MPS_TO_KMH = 3.6;
const MPS_TO_MPH = MPS_TO_KMH / KM_PER_MILE;

export type PaceSportKind = 'row' | 'run' | 'bike' | 'other';

export type { Units };

export function speedFromMps(metersPerSecond: number, units: Units): number {
  const v = Number(metersPerSecond);
  if (!Number.isFinite(v)) return 0;
  return units === 'imperial' ? v * MPS_TO_MPH : v * MPS_TO_KMH;
}

export function speedUnitLabel(units: Units): string {
  return units === 'imperial' ? 'mph' : 'km/h';
}

export function formatSpeedFromMps(
  metersPerSecond: number | null | undefined,
  units: Units,
  decimals = 1
): string {
  if (metersPerSecond == null || !Number.isFinite(metersPerSecond) || metersPerSecond <= 0) {
    return '—';
  }
  return `${speedFromMps(metersPerSecond, units).toFixed(decimals)} ${speedUnitLabel(units)}`;
}

export function coercePaceSport(sport: string): PaceSportKind {
  const s = (sport || '').toLowerCase();
  if (s === 'row' || s === 'rowing') return 'row';
  if (s === 'run' || s === 'running') return 'run';
  if (s === 'bike' || s === 'cycle' || s === 'cycling' || s === 'ride') return 'bike';
  return 'other';
}

/** Row/run: spm (strokes or steps per min). Bike: rpm. */
export function cadenceUnitLabel(sport: string): string {
  const k = coercePaceSport(sport);
  return k === 'row' || k === 'run' ? 'spm' : 'rpm';
}

export function cadenceChartTitle(sport: string): string {
  return coercePaceSport(sport) === 'row' ? 'Stroke Rate' : 'Cadence';
}

export function cadenceColumnHeader(sport: string): string {
  return `Cadence (${cadenceUnitLabel(sport)})`;
}

/** Rowing + running only; no pace chart for cycling. */
export function supportsPaceChart(sport: string): boolean {
  const k = coercePaceSport(sport);
  return k === 'row' || k === 'run';
}

/**
 * Pace as duration (seconds) per canonical segment from Strava velocity (m/s).
 * Row: 500 / v → sec per 500m
 * Run: 1000 / v (metric) or 1609.344 / v (imperial) → sec per km or mile
 */
export function paceSecondsFromVelocity(
  velocityMps: number,
  sport: string,
  units: Units = 'metric'
): number | null {
  if (!Number.isFinite(velocityMps) || velocityMps <= 0) return null;
  const kind = coercePaceSport(sport);
  if (kind === 'row') {
    const sec = 500 / velocityMps;
    if (sec > 600) return null;
    return sec;
  }
  if (kind === 'run') {
    const distM = units === 'imperial' ? METERS_PER_MILE : 1000;
    const sec = distM / velocityMps;
    if (sec > 3600) return null;
    return sec;
  }
  return null;
}

export function paceDistanceSuffix(sport: string, units: Units = 'metric'): string {
  const kind = coercePaceSport(sport);
  if (kind === 'row') return '/500m';
  if (kind === 'run') return units === 'imperial' ? '/mi' : '/km';
  return '';
}

export function paceChartTitle(sport: string, units: Units = 'metric'): string {
  const suffix = paceDistanceSuffix(sport, units);
  return suffix ? `Pace ${suffix}` : 'Pace';
}

export function formatPaceSeconds(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return '—';
  const r = Math.round(sec);
  const m = Math.floor(r / 60);
  const s = r % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatPaceWithSuffix(
  sec: number | null | undefined,
  sport: string,
  units: Units = 'metric'
): string {
  const base = formatPaceSeconds(sec);
  if (base === '—') return base;
  return `${base}${paceDistanceSuffix(sport, units)}`;
}

export function normalizeMeasurementUnits(raw: unknown): Units {
  return normalizeUnits(raw);
}

/** Drop GPS/velocity glitches before domain + render (pace in seconds). */
export function clampPaceSeries(values: number[]): {
  clamped: number[];
  lo: number;
  hi: number;
} {
  if (!values.length) {
    return { clamped: [], lo: 0, hi: 1 };
  }
  const sorted = [...values].sort((a, b) => a - b);
  const lo = d3.quantileSorted(sorted, PACE_QUANTILE_LO) ?? sorted[0];
  const hi = d3.quantileSorted(sorted, PACE_QUANTILE_HI) ?? sorted[sorted.length - 1];
  const clamped = values.map((v) => Math.min(hi, Math.max(lo, v)));
  return { clamped, lo, hi };
}

/** Faster (lower sec) toward top — Garmin/Strava-style inverted pace axis. */
export function invertedPaceYScale(
  yMin: number,
  yMax: number,
  chartHeight: number,
  padRatio = 0.08
): d3.ScaleLinear<number, number> {
  const pad = Math.max(2, (yMax - yMin) * padRatio);
  return d3
    .scaleLinear()
    .domain([yMax + pad, yMin - pad])
    .range([chartHeight, 0]);
}

/** Y-axis ticks: M:SS only (unit suffix is in chart title / unit label). */
export function formatPaceAxisTick(v: d3.NumberValue): string {
  return formatPaceSeconds(Number(v));
}
