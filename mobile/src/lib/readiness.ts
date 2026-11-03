/**
 * Readiness breakdown for the Readiness page. Mirrors the backend's
 * compute_readiness_score (algorithms.py): readiness = 0.7 × recovery + 0.3 × form,
 * where form is TSB squashed to 0–100 with a sigmoid (k = 0.055). Without a recovery
 * score the backend uses form alone.
 */

export const RECOVERY_WEIGHT = 0.7;
export const FORM_WEIGHT = 0.3;
const FORM_SIGMOID_K = 0.055;

export function formToScore(tsb: number): number {
  return 100 / (1 + Math.exp(-FORM_SIGMOID_K * tsb));
}

export type ReadinessBreakdown = {
  total: number;
  /** null when no recovery score was available (form-only readiness). */
  recovery: number | null;
  recoveryPart: number | null;
  formScore: number;
  formPart: number;
};

export function readinessBreakdown(recovery: number | null | undefined, tsb: number): ReadinessBreakdown {
  const formScore = formToScore(Number.isFinite(tsb) ? tsb : 0);
  const rec = recovery != null && Number.isFinite(recovery) && recovery > 0 ? recovery : null;
  if (rec == null) {
    return { total: Math.round(formScore), recovery: null, recoveryPart: null, formScore, formPart: formScore };
  }
  const recoveryPart = rec * RECOVERY_WEIGHT;
  const formPart = formScore * FORM_WEIGHT;
  return { total: Math.round(recoveryPart + formPart), recovery: rec, recoveryPart, formScore, formPart };
}

export type ReadinessBand = 'low' | 'mid' | 'high';

export function readinessBand(score: number): ReadinessBand {
  return score >= 67 ? 'high' : score >= 34 ? 'mid' : 'low';
}

export const BAND_COPY: Record<ReadinessBand, { verdict: string; range: string; action: string; color: string }> = {
  low: { verdict: 'Take it easy', range: '< 34', action: 'Swap to easy', color: 'var(--red)' },
  mid: { verdict: 'Train as planned', range: '34–66', action: 'As planned', color: 'var(--amber)' },
  high: { verdict: 'Ready to push', range: '≥ 67', action: 'Push if planned', color: 'var(--teal)' }
};

/** Mean and sample SD of the finite values. */
export function baseline(values: Array<number | null | undefined>): { mean: number; sd: number } | null {
  const v = values.filter((x): x is number => typeof x === 'number' && Number.isFinite(x));
  if (v.length === 0) return null;
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = v.length > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) : 0;
  return { mean, sd };
}

/**
 * Sparkline geometry for a 96×32 box: polyline points for the values (gaps skipped) and
 * a band for the baseline's ±1 SD, both on a shared scale.
 */
export function sparkline(
  values: Array<number | null | undefined>,
  base: { mean: number; sd: number } | null,
  width = 96,
  height = 32
): { points: string; bandY: number; bandH: number } | null {
  const idx = values.map((v, i) => [v, i] as const).filter((p): p is readonly [number, number] => typeof p[0] === 'number' && Number.isFinite(p[0]));
  if (idx.length < 2) return null;
  const lo0 = base ? base.mean - base.sd : Infinity;
  const hi0 = base ? base.mean + base.sd : -Infinity;
  let min = Math.min(lo0, ...idx.map((p) => p[0]));
  let max = Math.max(hi0, ...idx.map((p) => p[0]));
  if (max - min < 1e-6) {
    min -= 1;
    max += 1;
  }
  const n = values.length;
  const x = (i: number) => Math.round((i * (width - 4)) / Math.max(n - 1, 1) + 2);
  const y = (v: number) => Math.round(height - 2 - ((v - min) / (max - min)) * (height - 4));
  const points = idx.map(([v, i]) => `${x(i)},${y(v)}`).join(' ');
  if (!base) return { points, bandY: 0, bandH: 0 };
  const top = y(base.mean + base.sd);
  const bottom = y(base.mean - base.sd);
  return { points, bandY: top, bandH: Math.max(bottom - top, 2) };
}
