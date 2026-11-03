/**
 * Geometry for the wide Training log splits chart (design: WSplits): one bar per lap,
 * bar width proportional to lap duration, height = average power (or speed when there's
 * no power), with average heart rate as a line through the lap centres.
 */
import type { ActivitySplit } from '$lib/utils/lapSplits';

export type SplitBar = { x: number; y: number; w: number; h: number; cx: number; hy: number | null };

export type SplitChart = {
  bars: SplitBar[];
  /** SVG polyline points for laps that have heart rate. */
  hrLine: string;
  metric: 'power' | 'speed';
};

function speedOf(s: ActivitySplit): number {
  if (Number(s.average_speed) > 0) return Number(s.average_speed);
  return s.distance > 0 && s.elapsed_time > 0 ? s.distance / s.elapsed_time : 0;
}

/** Null when there are fewer than two laps or nothing to plot. */
export function buildSplitChart(splits: ActivitySplit[], width: number, height: number, gap = 3): SplitChart | null {
  if (!splits || splits.length < 2 || width <= 0 || height <= 0) return null;
  const metric: 'power' | 'speed' = splits.some((s) => Number(s.average_watts) > 0) ? 'power' : 'speed';
  const value = (s: ActivitySplit) => (metric === 'power' ? Number(s.average_watts) || 0 : speedOf(s));
  const vals = splits.map(value);
  const vMax = Math.max(...vals);
  if (!(vMax > 0)) return null;

  const durs = splits.map((s) => Math.max(1, Number(s.elapsed_time) || 0));
  const total = durs.reduce((a, b) => a + b, 0);
  const usable = width - gap * (splits.length - 1);
  if (usable <= 0) return null;

  const hrs = splits.map((s) => (Number(s.average_heartrate) > 0 ? Number(s.average_heartrate) : null));
  const hrKnown = hrs.filter((h): h is number => h != null);
  const hrMin = hrKnown.length ? Math.min(...hrKnown) : 0;
  const hrMax = hrKnown.length ? Math.max(...hrKnown) : 0;
  const hrSpan = Math.max(hrMax - hrMin, 1);
  // HR line in the top 70% of the chart, so it reads over the bars.
  const hrY = (h: number) => Math.round((height * 0.1 + (1 - (h - hrMin) / hrSpan) * height * 0.6) * 10) / 10;

  let x = 0;
  const bars: SplitBar[] = splits.map((_, i) => {
    const w = Math.max(1, (durs[i] / total) * usable);
    const h = Math.max(2, (vals[i] / vMax) * (height - 4));
    const bar: SplitBar = {
      x: Math.round(x * 10) / 10,
      y: Math.round((height - h) * 10) / 10,
      w: Math.round(w * 10) / 10,
      h: Math.round(h * 10) / 10,
      cx: Math.round((x + w / 2) * 10) / 10,
      hy: hrs[i] == null ? null : hrY(hrs[i]!)
    };
    x += w + gap;
    return bar;
  });
  const hrLine = bars
    .filter((b) => b.hy != null)
    .map((b) => `${b.cx},${b.hy}`)
    .join(' ');
  return { bars, hrLine, metric };
}
