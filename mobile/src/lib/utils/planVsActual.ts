/**
 * Planned vs actual for a linked workout (design: PvA option F, "windows + list").
 *
 * Each planned block gets a target window (power from % FTP, or heart rate from the athlete's
 * zones). The recorded stream is cut into the blocks by elapsed time, and every sample is
 * counted as below, in or above its block's window. The panel draws the windows over zone
 * bands with the trace coloured by fit, and lists the blocks with their split.
 */
import type { Interval } from '$lib/types/training';
import { zoneForFtpPct } from '$lib/components/wide/today/todayWide';
import { powerBand } from '$lib/utils/powerBand';

export type Metric = 'power' | 'hr';
export type Fit = 'below' | 'in' | 'above' | 'none';

export interface ZoneDefLike {
  zone: number;
  min_bpm: number;
  max_bpm: number;
}

export interface Stream {
  values?: number[];
  time?: number[];
  step?: number;
}

export interface TargetWindow {
  lo: number;
  hi: number;
  zone: number;
  /** e.g. "Z4 · 225–245 W" or "Z1 · < 136 bpm". */
  label: string;
}

export interface BlockStats {
  /** Seconds recorded in this block. */
  secs: number;
  /** Seconds that count toward the fit (HR skips each block's first 60 s while it catches up). */
  fitSecs: number;
  below: number;
  inn: number;
  above: number;
  avg: number | null;
  min: number | null;
  max: number | null;
}

export interface PvaBlock {
  i: number;
  name: string;
  /** Start and length in minutes from the start of the workout. */
  t0: number;
  min: number;
  window: TargetWindow | null;
  stats: BlockStats;
}

/** Power zones as % FTP (Coggan), Z1..Z5. */
export const POWER_ZONE_PCT: [number, number][] = [
  [0, 55],
  [56, 75],
  [76, 90],
  [91, 105],
  [106, 150]
];


const round5 = (v: number) => Math.round(v / 5) * 5;

function rangeLabel(zone: number, lo: number, hi: number, unit: string): string {
  return `Z${zone} · ${lo <= 0 ? `< ${hi}` : `${lo}–${hi}`} ${unit}`;
}

/** The block's target window for `metric`, or null when the plan or profile can't give one. */
export function targetWindow(block: Interval, metric: Metric, ftp: number, zones: ZoneDefLike[]): TargetWindow | null {
  const pct = typeof block.target_power_percent_ftp === 'number' && block.target_power_percent_ftp > 0 ? block.target_power_percent_ftp : null;
  const hrZone = typeof block.target_hr_zone === 'number' && block.target_hr_zone > 0 ? Math.min(5, Math.round(block.target_hr_zone)) : null;
  if (metric === 'power') {
    if (!(ftp > 0)) return null;
    if (pct != null) {
      // A ±5% FTP window around the prescribed power.
      const [lo, hi] = powerBand(ftp, pct);
      const zone = zoneForFtpPct(pct);
      return { lo, hi, zone, label: rangeLabel(zone, lo, hi, 'W') };
    }
    if (hrZone != null) {
      const [a, b] = POWER_ZONE_PCT[hrZone - 1];
      const lo = hrZone === 1 ? 0 : round5((ftp * a) / 100);
      const hi = round5((ftp * b) / 100);
      return { lo, hi, zone: hrZone, label: rangeLabel(hrZone, lo, hi, 'W') };
    }
    return null;
  }
  const zone = hrZone ?? (pct != null ? zoneForFtpPct(pct) : null);
  const def = zone != null ? zones.find((z) => z.zone === zone) : undefined;
  if (zone == null || !def || !(def.max_bpm > 0)) return null;
  const lo = zone === 1 ? 0 : Math.round(def.min_bpm);
  const hi = Math.round(def.max_bpm);
  return { lo, hi, zone, label: rangeLabel(zone, lo, hi, 'bpm') };
}

/** Planned blocks with their start times (blocks without a duration are skipped). */
export function timeline(structure: Interval[]): { b: Interval; t0: number; min: number }[] {
  const out: { b: Interval; t0: number; min: number }[] = [];
  let t = 0;
  for (const b of structure) {
    const min = Math.max(0, Number(b.duration_minutes) || 0);
    if (!min) continue;
    out.push({ b, t0: t, min });
    t += min;
  }
  return out;
}

export function fitOf(v: number, w: TargetWindow | null): Fit {
  if (!w || !Number.isFinite(v)) return 'none';
  return v > w.hi ? 'above' : v < w.lo ? 'below' : 'in';
}

/** Elapsed seconds and duration of each sample (gaps longer than 30 s count as 30 s). */
function samples(s: Stream): { t: number; dt: number; v: number }[] {
  const vals = s.values ?? [];
  const step = s.step || 1;
  const out: { t: number; dt: number; v: number }[] = [];
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i];
    if (!Number.isFinite(v)) continue;
    const t = s.time?.[i] ?? i * step;
    const next = s.time?.[i + 1];
    const dt = next != null ? Math.min(Math.max(next - t, 0), 30) : step;
    out.push({ t, dt, v });
  }
  return out;
}

const HR_GRACE_SEC = 60;
/** Power is judged on a 30-s rolling average: second-by-second trainer power swings ±15-20 W, so
 * raw samples put a ride steadily inside a ±5% FTP window "46% in target". */
export const POWER_SMOOTH_SEC = 30;

/** Time-weighted trailing average over `windowSec` (restarting at the first sample given). */
export function rollingMean(pts: { t: number; dt: number; v: number }[], windowSec: number): number[] {
  const out: number[] = [];
  let sum = 0;
  let wsum = 0;
  let j = 0;
  for (let i = 0; i < pts.length; i++) {
    sum += pts[i].v * pts[i].dt;
    wsum += pts[i].dt;
    while (j < i && pts[i].t - pts[j].t >= windowSec) {
      sum -= pts[j].v * pts[j].dt;
      wsum -= pts[j].dt;
      j++;
    }
    out.push(wsum > 0 ? sum / wsum : pts[i].v);
  }
  return out;
}

export function blockStats(stream: Stream, t0Min: number, min: number, w: TargetWindow | null, metric: Metric): BlockStats {
  const start = t0Min * 60;
  const end = (t0Min + min) * 60;
  let secs = 0, fitSecs = 0, below = 0, inn = 0, above = 0, sum = 0;
  let lo: number | null = null, hi: number | null = null;
  const inBlock = samples(stream).filter(({ t }) => t >= start && t < end);
  // What's judged against the target: smoothed power (within the block), raw heart rate.
  const judged = metric === 'power' ? rollingMean(inBlock, POWER_SMOOTH_SEC) : inBlock.map((p) => p.v);
  for (let k = 0; k < inBlock.length; k++) {
    const { t, dt, v } = inBlock[k];
    secs += dt;
    sum += v * dt;
    lo = lo == null ? v : Math.min(lo, v);
    hi = hi == null ? v : Math.max(hi, v);
    if (!w || (metric === 'hr' && t - start < HR_GRACE_SEC)) continue;
    fitSecs += dt;
    const f = fitOf(judged[k], w);
    if (f === 'below') below += dt;
    else if (f === 'above') above += dt;
    else inn += dt;
  }
  return { secs, fitSecs, below, inn, above, avg: secs ? Math.round(sum / secs) : null, min: lo, max: hi };
}

export function pvaBlocks(structure: Interval[], stream: Stream, metric: Metric, ftp: number, zones: ZoneDefLike[]): PvaBlock[] {
  return timeline(structure).map(({ b, t0, min }, i) => {
    const window = targetWindow(b, metric, ftp, zones);
    return { i, name: b.name || `Block ${i + 1}`, t0, min, window, stats: blockStats(stream, t0, min, window, metric) };
  });
}

/** Share of fit time in target across blocks with a window (null when nothing counted). */
export function inTargetPct(blocks: PvaBlock[]): number | null {
  const fit = blocks.reduce((a, b) => a + b.stats.fitSecs, 0);
  if (!fit) return null;
  return Math.round((blocks.reduce((a, b) => a + b.stats.inn, 0) / fit) * 100);
}

export const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

/** Value range of the chart's y axis. */
export function yRange(metric: Metric, ftp: number, zones: ZoneDefLike[]): [number, number] {
  if (metric === 'power') return [Math.round(ftp * 0.35), Math.round(ftp * 1.25)];
  const z1 = zones.find((z) => z.zone === 1);
  const z4 = zones.find((z) => z.zone === 4);
  const lo = z1?.max_bpm ? Math.max(60, Math.round(z1.max_bpm - 35)) : 100;
  const hi = z4?.max_bpm ? Math.round(z4.max_bpm + 15) : 200;
  return hi > lo ? [lo, hi] : [100, 200];
}

/** Zone bands (value ranges) for the chart background. */
export function zoneBands(metric: Metric, ftp: number, zones: ZoneDefLike[]): { zone: number; lo: number; hi: number }[] {
  if (metric === 'power') {
    return POWER_ZONE_PCT.map(([a, b], i) => ({ zone: i + 1, lo: (ftp * a) / 100, hi: (ftp * (i === 4 ? 200 : b)) / 100 }));
  }
  return [...zones]
    .filter((z) => z.zone >= 1 && z.zone <= 5 && z.max_bpm > 0)
    .sort((a, b) => a.zone - b.zone)
    .map((z) => ({ zone: z.zone, lo: z.zone === 1 ? 0 : z.min_bpm, hi: z.zone === 5 ? 250 : z.max_bpm }));
}

/** Downsampled trace: average per bucket at the bucket's middle time, with its fit. */
export function tracePoints(
  stream: Stream,
  blocks: PvaBlock[],
  buckets = 160
): { tMin: number; v: number; fit: Fit }[] {
  const pts = samples(stream);
  if (pts.length < 2) return [];
  const per = Math.max(1, Math.ceil(pts.length / buckets));
  const out: { tMin: number; v: number; fit: Fit }[] = [];
  for (let i = 0; i < pts.length; i += per) {
    const chunk = pts.slice(i, i + per);
    const v = chunk.reduce((a, p) => a + p.v, 0) / chunk.length;
    const tMin = chunk[Math.floor(chunk.length / 2)].t / 60;
    const b = blocks.find((x) => tMin >= x.t0 && tMin < x.t0 + x.min);
    out.push({ tMin, v, fit: b ? fitOf(v, b.window) : 'none' });
  }
  return out;
}

/** Minutes as the design's short form: 54′ (or 1h05 from an hour). */
export function mins(m: number): string {
  const r = Math.round(m);
  return r >= 60 ? `${Math.floor(r / 60)}h${String(r % 60).padStart(2, '0')}` : `${r}′`;
}

/**
 * A heart rate placed on the power chart by zone ("Both"): a value in HR zone z is drawn in
 * power zone z's band, at the same relative position within the zone. So HR in Z2 sits in the
 * Z2 band whatever the bpm numbers are. Null without HR zones.
 */
export function hrOnPowerScale(bpm: number, ftp: number, zones: ZoneDefLike[]): number | null {
  const hr = zoneBands('hr', ftp, zones);
  if (hr.length < 5 || !(ftp > 0) || !Number.isFinite(bpm)) return null;
  const power = zoneBands('power', ftp, zones);
  const [hrLo] = yRange('hr', ftp, zones);
  const [pLo, pHi] = yRange('power', ftp, zones);
  const i = hr.findIndex((z) => bpm < z.hi);
  const z = hr[i === -1 ? hr.length - 1 : i];
  const pz = power[z.zone - 1];
  // Zone 1 starts at the chart floor; zone 5 ends at the chart top.
  const lo = z.zone === 1 ? hrLo : z.lo;
  const hi = z.zone === 5 ? Math.max(z.lo + 1, zones.find((d) => d.zone === 5)?.max_bpm ?? z.lo + 20) : z.hi;
  const plo = z.zone === 1 ? pLo : pz.lo;
  const phi = z.zone === 5 ? pHi : pz.hi;
  const t = Math.max(0, Math.min(1, (bpm - lo) / Math.max(1, hi - lo)));
  return plo + t * (phi - plo);
}
