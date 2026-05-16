import type { ActivityLap, ActivityStreams } from '$lib/services/activityService';

export type Point = { t: number; v: number };

export const ZONE_COLORS: Record<number, string> = {
  1: '#579BFA',
  2: '#00C8A8',
  3: '#FFCB88',
  4: '#FF8C42',
  5: '#F07178',
};

export const ZONE_NAMES: Record<number, string> = {
  1: 'Active Recovery',
  2: 'Endurance',
  3: 'Tempo',
  4: 'Threshold',
  5: 'VO2max+',
};

export const CHART_LEFT = 40;
export const CHART_HEIGHT = 150;

export const PACE_CAP_ROW = 300; // s/500m
export const PACE_CAP_RUN = 600; // s/km
export const TIME_GAP_SEC = 30;

export function isMovingIndex(i: number, moving?: boolean[]): boolean {
  if (!moving?.length) return true;
  return moving[i] !== false;
}

export type ZipStreamOpts = {
  requireMoving?: boolean;
  moving?: boolean[];
  maxValue?: number;
  minValue?: number;
};

export function zip(
  time: number[] | undefined,
  arr: number[] | undefined,
  opts?: ZipStreamOpts
): Point[] {
  if (!time?.length || !arr?.length) return [];
  const n = Math.min(time.length, arr.length);
  const out: Point[] = [];
  for (let i = 0; i < n; i++) {
    if (opts?.requireMoving && !isMovingIndex(i, opts.moving)) continue;
    const v = arr[i];
    if (v == null || !Number.isFinite(v)) continue;
    if (opts?.minValue != null && v < opts.minValue) continue;
    if (opts?.maxValue != null && v > opts.maxValue) continue;
    out.push({ t: time[i], v });
  }
  return out;
}

export function buildPacePoints(
  time: number[] | undefined,
  velocity: number[] | undefined,
  sport: string,
  moving?: boolean[]
): Point[] {
  if (!time?.length || !velocity?.length) return [];
  const isRow = sport === 'row';
  const velMin = isRow ? 1.0 : 0.5;
  const paceCap = isRow ? PACE_CAP_ROW : PACE_CAP_RUN;
  const out: Point[] = [];
  const n = Math.min(time.length, velocity.length);
  for (let i = 0; i < n; i++) {
    if (!isMovingIndex(i, moving)) continue;
    const v = velocity[i];
    if (v == null || !Number.isFinite(v) || v < velMin) continue;
    const pace = isRow ? 500 / v : 1000 / v;
    if (pace > paceCap) continue;
    out.push({ t: time[i], v: pace });
  }
  return out;
}

export function hrToZone(bpm: number): 1 | 2 | 3 | 4 | 5 {
  if (bpm < 138) return 1;
  if (bpm <= 154) return 2;
  if (bpm <= 167) return 3;
  if (bpm <= 177) return 4;
  return 5;
}

export function splitZoneRuns(
  points: (Point & { zone: number; color: string })[]
): { zone: number; color: string; data: Point[] }[] {
  if (points.length === 0) return [];
  const runs: { zone: number; color: string; data: Point[] }[] = [];
  let cur = points[0].zone;
  let buf: Point[] = [{ t: points[0].t, v: points[0].v }];

  for (let i = 1; i < points.length; i++) {
    const p = points[i];
    if (p.zone !== cur && buf.length) {
      const bridge = { t: p.t, v: p.v };
      buf.push(bridge);
      runs.push({ zone: cur, color: ZONE_COLORS[cur], data: buf });
      buf = [bridge];
      cur = p.zone;
    }
    buf.push({ t: p.t, v: p.v });
  }
  if (buf.length) runs.push({ zone: cur, color: ZONE_COLORS[cur], data: buf });
  return runs;
}

/** Split a point series when elapsed time jumps (stopped segments). */
export function splitByTimeGaps(points: Point[], maxGapSec = TIME_GAP_SEC): Point[][] {
  if (points.length === 0) return [];
  const segments: Point[][] = [];
  let buf: Point[] = [points[0]];

  for (let i = 1; i < points.length; i++) {
    const gap = points[i].t - points[i - 1].t;
    if (gap > maxGapSec) {
      if (buf.length) segments.push(buf);
      buf = [];
    }
    buf.push(points[i]);
  }
  if (buf.length) segments.push(buf);
  return segments;
}

export type LapMarker = { lapIndex: number; t: number };

/** Vertical lap lines; keyed by lap_index (Strava may repeat start_index across laps). */
export function lapMarkers(streams: ActivityStreams, laps: ActivityLap[]): LapMarker[] {
  const time = streams.time_series.time;
  if (!time?.length) return [];
  const out: LapMarker[] = [];
  for (const lap of laps) {
    const lapIndex = lap.lap_index;
    if (lapIndex == null || lapIndex <= 0) continue;
    const t = time[lap.start_index ?? 0];
    if (t == null || !Number.isFinite(t)) continue;
    out.push({ lapIndex, t });
  }
  return out;
}

export function formatTimeAxis(minutes: number, maxMinutes: number): string {
  if (maxMinutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return `${h}:${String(m).padStart(2, '0')}`;
  }
  return `${Math.round(minutes)}m`;
}

export function nearestTime(points: Point[], tSec: number): number | null {
  if (!points.length) return null;
  let best = points[0].t;
  let bestD = Math.abs(points[0].t - tSec);
  for (const p of points) {
    const d = Math.abs(p.t - tSec);
    if (d < bestD) {
      bestD = d;
      best = p.t;
    }
  }
  return best;
}

/** Crosshair snap against the master timeline (seconds). */
export function nearestTimeOnTimeline(tSec: number, time: number[]): number | null {
  if (!time.length) return null;
  let best = time[0];
  let bestD = Math.abs(time[0] - tSec);
  for (const t of time) {
    const d = Math.abs(t - tSec);
    if (d < bestD) {
      bestD = d;
      best = t;
    }
  }
  return best;
}

/** Index into the master time array for shared crosshair. */
export function nearestTimeIndex(tSec: number, time: number[]): number | null {
  if (!time.length) return null;
  let bestIdx = 0;
  let bestD = Math.abs(time[0] - tSec);
  for (let i = 1; i < time.length; i++) {
    const d = Math.abs(time[i] - tSec);
    if (d < bestD) {
      bestD = d;
      bestIdx = i;
    }
  }
  return bestIdx;
}

/** Thin lap lines when there are many laps; always include the final lap. */
export function filterLapMarkersForDisplay(markers: LapMarker[]): LapMarker[] {
  if (markers.length <= 12) return markers;
  const sorted = [...markers].sort((a, b) => a.t - b.t);
  const last = sorted[sorted.length - 1];
  const thinned = sorted.filter((_, i) => i % 2 === 0);
  if (!thinned.some((m) => m.lapIndex === last.lapIndex && m.t === last.t)) {
    thinned.push(last);
  }
  return thinned;
}

export function lapXpx(lapTimeSec: number, maxTMin: number, innerWidth: number): number {
  if (maxTMin <= 0) return CHART_LEFT;
  const xPct = lapTimeSec / 60 / maxTMin;
  return CHART_LEFT + xPct * innerWidth;
}

export function crosshairXpx(hoverTimeSec: number, maxTMin: number, innerWidth: number): number {
  return lapXpx(hoverTimeSec, maxTMin, innerWidth);
}

/** Flatten zone runs after gap-splitting for LayerChart series. */
export function zoneRunsWithGaps(
  zoned: (Point & { zone: number; color: string })[]
): { zone: number; color: string; data: Point[] }[] {
  const runs = splitZoneRuns(zoned);
  const out: { zone: number; color: string; data: Point[] }[] = [];
  for (const run of runs) {
    const segments = splitByTimeGaps(run.data);
    for (const seg of segments) {
      if (seg.length >= 2) {
        out.push({ zone: run.zone, color: run.color, data: seg });
      }
    }
  }
  return out;
}

export function downsamplePoints(pts: Point[], resolutionSeconds: number, maxPoints = 1000): Point[] {
  if (resolutionSeconds !== 1 || pts.length <= maxPoints) return pts;
  return pts.filter((_, i) => i % 2 === 0);
}
