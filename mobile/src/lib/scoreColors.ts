// ASTRAPE color rules — centralized semantic styling.
//
// High-level metrics (recovery/sleep/strain scores, form/TSB, z-scores) map
// to tailwind-compatible classes (`text-astrape-*`). Many raw physiologic values
// on dashboard / vitals intentionally inherit their *underlying* semantic
// quality (sleep duration → sleep score band, HRV ms → z-score bands, workout
// TSS → strain band) per the current product spec.

export type ScoreTone = 'teal' | 'blue' | 'amber' | 'red' | 'muted';

const toneToTextClass: Record<ScoreTone, string> = {
  teal: 'text-astrape-teal',
  blue: 'text-astrape-blue',
  amber: 'text-astrape-amber',
  red: 'text-astrape-red',
  muted: 'text-text2'
};

const toneToCssVar: Record<ScoreTone, string> = {
  teal: 'var(--teal)',
  blue: 'var(--blue)',
  amber: 'var(--amber)',
  red: 'var(--red)',
  muted: 'var(--text2)'
};

export const NEUTRAL_TEXT_CLASS = 'text-text0';
export const NEUTRAL_CSS_COLOR = 'var(--text0)';

export function cssVarFor(tone: ScoreTone): string {
  return toneToCssVar[tone];
}

export function textClassFor(tone: ScoreTone): string {
  return toneToTextClass[tone];
}

function toNumber(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

// ---------------------------------------------------------------------------
// 0-100 bounded scores (Strain / Recovery / Sleep) — strict rule of thirds.
// `isInverted=true` flips the bands for metrics where lower is better (e.g.
// Strain): >=67 red, 34-66 amber, <=33 teal.
// ---------------------------------------------------------------------------
export function boundedScoreTone(score: unknown, isInverted = false): ScoreTone {
  const s = toNumber(score);
  if (s == null) return 'muted';
  if (isInverted) {
    if (s >= 67) return 'red';
    if (s >= 34) return 'amber';
    return 'teal';
  }
  if (s >= 67) return 'teal';
  if (s >= 34) return 'amber';
  return 'red';
}

export function getBoundedScoreColor(score: unknown, isInverted = false): string {
  return toneToTextClass[boundedScoreTone(score, isInverted)];
}

export function boundedScoreCssColor(score: unknown, isInverted = false): string {
  return toneToCssVar[boundedScoreTone(score, isInverted)];
}

// ---------------------------------------------------------------------------
// TSB (Training Stress Balance / Form) — four bands (Teal / Amber / Red / Blue).
//   > +25  -> blue    (detraining / transition)
//   >= -10 -> teal    (fresh / productive)
//   >= -30 -> amber   (elevated fatigue / building risk)
//   < -30  -> red     (high risk / overreaching)
// ---------------------------------------------------------------------------
export function formTone(tsb: unknown): ScoreTone {
  const t = toNumber(tsb);
  if (t == null) return 'muted';
  if (t > 25) return 'blue';
  if (t >= -10) return 'teal';
  if (t >= -30) return 'amber';
  return 'red';
}

// Canvas / SVG identity colors for CTL (fitness line) vs ATL (fatigue bars).
// Matches Tailwind `blue-500` and slate-700 at ~50% fill opacity.
export const CHART_CTL_STROKE = '#3b82f6';
/** chartAtl token hex — canvas, LayerChart, MetricBadge color prop only */
export const CHART_ATL_STROKE = '#334155';
export const CHART_ATL_FILL_REST = 'rgba(51, 65, 85, 0.5)';
export const CHART_ATL_FILL_ACTIVE = 'rgba(51, 65, 85, 0.65)';

export function getFormColor(tsb: unknown): string {
  return toneToTextClass[formTone(tsb)];
}

export function formCssColor(tsb: unknown): string {
  return toneToCssVar[formTone(tsb)];
}

// ---------------------------------------------------------------------------
// Sleep Debt (minutes accumulated).
//   < 45  -> teal
//   45-90 -> amber
//   > 90  -> red
// ---------------------------------------------------------------------------
export function sleepDebtTone(debtMin: unknown): ScoreTone {
  const m = toNumber(debtMin);
  if (m == null) return 'muted';
  if (m < 45) return 'teal';
  if (m <= 90) return 'amber';
  return 'red';
}

export function getSleepDebtColor(debtMin: unknown): string {
  return toneToTextClass[sleepDebtTone(debtMin)];
}

export function sleepDebtCssColor(debtMin: unknown): string {
  return toneToCssVar[sleepDebtTone(debtMin)];
}

// ---------------------------------------------------------------------------
// Z-score deviation indicator (HRV/RHR).
// HRV (default): higher is better.
//   z >  -0.5         -> teal (stable / optimal)
//   -1.5 <= z <= -0.5 -> amber (suppressed)
//   z <  -1.5         -> red   (severe drop)
// RHR (inverted: higher is worse). Equivalent to negating the z before checks:
//   z <  0.5          -> teal
//   0.5 <= z <= 1.5   -> amber
//   z >  1.5          -> red
// ---------------------------------------------------------------------------
export function zScoreTone(z: unknown, isInverted = false): ScoreTone {
  const raw = toNumber(z);
  if (raw == null) return 'muted';
  const norm = isInverted ? -raw : raw;
  if (norm > -0.5) return 'teal';
  if (norm >= -1.5) return 'amber';
  return 'red';
}

export function getZScoreColor(z: unknown, isInverted = false): string {
  return toneToTextClass[zScoreTone(z, isInverted)];
}

export function zScoreCssColor(z: unknown, isInverted = false): string {
  return toneToCssVar[zScoreTone(z, isInverted)];
}

// ---------------------------------------------------------------------------
// Weekly load: delta coloring vs trailing baseline (fractional overload).
// Argument is (currentRolling7d − baselineRollingAvg) / max(baseline, ε).
// ---------------------------------------------------------------------------
export function weeklyLoadDeltaTone(pctVsBaseline: unknown): ScoreTone {
  const r = toNumber(pctVsBaseline);
  if (r == null) return 'muted';
  if (r >= 0.35) return 'red';
  if (r >= 0.18) return 'amber';
  if (r <= -0.18) return 'teal';
  return 'muted';
}

export function getWeeklyLoadDeltaColor(pctVsBaseline: unknown): string {
  return toneToTextClass[weeklyLoadDeltaTone(pctVsBaseline)];
}

// ---------------------------------------------------------------------------
// Backwards-compatibility shims (strain* aliases).
// ---------------------------------------------------------------------------
export const strainTone = boundedScoreTone;
export const strainTextClass = getBoundedScoreColor;
export const strainCssColor = boundedScoreCssColor;

/** Prefer `getBoundedScoreColor(strain, true)` in UI; kept for readability at call sites */
export function tssToneFromStrain(strainScore: unknown): ScoreTone {
  return boundedScoreTone(strainScore, true);
}

export function workoutOutputTextClass(strainScore: unknown): string {
  return getBoundedScoreColor(strainScore, true);
}
