/**
 * Astraphe Biometric Intelligence
 * Custom algorithms for Sleep and Recovery scoring
 */

import { format } from 'date-fns';

const STALE_AFTER_HOURS = 36;

export type BiometricsRow = Record<string, unknown>;

export type CurrentRecoveryState = {
  row: BiometricsRow | null;
  date: string | null;
  hasTodayRow: boolean;
  isStale: boolean;
  ageHours: number | null;
};

export function firstPositiveFiniteNumber(...candidates: unknown[]): number | null {
  for (const v of candidates) {
    if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v;
    if (typeof v === 'string' && v.trim() !== '') {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) return n;
    }
  }
  return null;
}

function finiteRecoveryScore(row: BiometricsRow | null | undefined): number | null {
  if (!row) return null;
  const n = Number(row.recovery_score);
  return Number.isFinite(n) ? n : null;
}

function rowWakeMs(row: BiometricsRow, timezoneOffsetMin: number): number | null {
  const wakeup = row.sleep_wakeup;
  if (typeof wakeup === 'string' && wakeup.trim() !== '') {
    const t = Date.parse(wakeup);
    if (Number.isFinite(t)) return t;
  }
  const dateStr = typeof row.date === 'string' ? row.date.slice(0, 10) : null;
  if (!dateStr) return null;
  const offset = timezoneOffsetMin ?? 0;
  const t = Date.parse(`${dateStr}T00:00:00`) - offset * 60_000;
  return Number.isFinite(t) ? t : null;
}

function latestRowWithRecovery(series: BiometricsRow[]): BiometricsRow | null {
  let best: BiometricsRow | null = null;
  let bestDate = '';
  for (const row of series) {
    if (finiteRecoveryScore(row) === null) continue;
    const d = typeof row.date === 'string' ? row.date.slice(0, 10) : '';
    if (!d || d < bestDate) continue;
    bestDate = d;
    best = row;
  }
  return best;
}

/**
 * Readiness-style score from a biometrics row (readiness first, then recovery).
 */
export function readinessScoreFromRow(row: BiometricsRow | null | undefined): number | null {
  if (!row) return null;
  return firstPositiveFiniteNumber(row.readiness_score, row.recovery_score);
}

/**
 * Resolves the biometrics row to treat as the athlete's *current* recovery state.
 * Prefers today's row when it has a finite recovery_score; otherwise carries forward
 * the most recent such row. Flags staleness so the UI doesn't present old data as live.
 */
export function currentRecoveryState(
  series: Array<BiometricsRow> | undefined,
  timezoneOffsetMin: number | null | undefined,
  now: Date = new Date()
): CurrentRecoveryState {
  const empty: CurrentRecoveryState = {
    row: null,
    date: null,
    hasTodayRow: false,
    isStale: false,
    ageHours: null
  };

  const rows = series ?? [];
  if (rows.length === 0) return empty;

  const offset = timezoneOffsetMin ?? 0;
  const deviceLocalToday = format(now, 'yyyy-MM-dd');

  const todayRow = rows.find(
    (r) => typeof r.date === 'string' && r.date.slice(0, 10) === deviceLocalToday
  );
  if (todayRow && finiteRecoveryScore(todayRow) !== null) {
    return {
      row: todayRow,
      date: deviceLocalToday,
      hasTodayRow: true,
      isStale: false,
      ageHours: 0
    };
  }

  const latest = latestRowWithRecovery(rows);
  if (!latest) return empty;

  const latestDate = typeof latest.date === 'string' ? latest.date.slice(0, 10) : null;
  const wakeMs = rowWakeMs(latest, offset);
  const ageHours =
    wakeMs !== null ? Math.max(0, (now.getTime() - wakeMs) / 3_600_000) : null;
  const isStale = ageHours !== null && ageHours > STALE_AFTER_HOURS;

  return {
    row: latest,
    date: latestDate,
    hasTodayRow: false,
    isStale,
    ageHours
  };
}

export interface SleepData {
  durationMin: number;
  deepPct: number;
  remPct: number;
  lightPct: number;
  awakePct: number;
}

export interface RecoveryData {
  hrv: number;
  restingHr: number;
  sleepScore: number;
  hrvBaseline: number;
  rhrBaseline: number;
}

/**
 * Calculates a custom Astraphe Sleep Score (0-100)
 * Weights: 60% Duration, 40% Quality (REM + Deep)
 */
export function calculateSleepScore(data: SleepData): number {
  if (!data.durationMin) return 0;

  // 1. Duration Score (Goal: 8 hours / 480 mins)
  const durationScore = Math.min(100, (data.durationMin / 480) * 100);

  // 2. Quality Score (Goal: REM + Deep >= 45% of total)
  const qualityPct = (data.remPct || 0) + (data.deepPct || 0);
  const qualityScore = Math.min(100, (qualityPct / 45) * 100);

  return Math.round((durationScore * 0.6) + (qualityScore * 0.4));
}

/**
 * Resolve display weight (kg): newest in loaded biometrics series, then
 * profile.latest_weight_kg (full history from API), then athletes.weight_kg.
 */
export function latestWeightKg(
  series: Array<{ weight_kg?: unknown }> | null | undefined,
  profileWeightKg: unknown,
  latestWeightKgFromProfile?: unknown
): number | null {
  const rows = series ?? [];
  for (let i = rows.length - 1; i >= 0; i--) {
    const w = Number(rows[i]?.weight_kg);
    if (Number.isFinite(w) && w > 0) return w;
  }
  const fromBiometrics = Number(latestWeightKgFromProfile);
  if (Number.isFinite(fromBiometrics) && fromBiometrics > 0) return fromBiometrics;
  const profile = Number(profileWeightKg);
  if (Number.isFinite(profile) && profile > 0) return profile;
  return null;
}

/**
 * Calculates a custom Astraphe Recovery Score (0-100)
 * Weights: 45% HRV, 25% RHR, 30% Sleep
 */
export function calculateRecoveryScore(data: RecoveryData): number {
  // 1. HRV Score (Relative to baseline)
  // Higher is better. 100 points if HRV >= Baseline + 10%
  const hrvRatio = data.hrv / (data.hrvBaseline || 50);
  const hrvScore = Math.min(100, Math.max(0, hrvRatio * 75)); // Scaled conservative

  // 2. RHR Score (Relative to baseline)
  // Lower is better. 100 points if RHR <= Baseline - 5%
  const rhrDiff = (data.rhrBaseline || 60) - data.restingHr;
  const rhrScore = Math.min(100, Math.max(0, 50 + (rhrDiff * 5))); // 50 is baseline, +/- 5 points per bpm

  // 3. Sleep contribution
  const sleepContrib = data.sleepScore;

  return Math.round((hrvScore * 0.45) + (rhrScore * 0.25) + (sleepContrib * 0.3));
}
