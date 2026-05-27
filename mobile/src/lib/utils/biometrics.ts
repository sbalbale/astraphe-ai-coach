/**
 * Astrape Biometric Intelligence
 * Custom algorithms for Sleep and Recovery scoring
 */

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
 * Calculates a custom Astrape Sleep Score (0-100)
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
 * Calculates a custom Astrape Recovery Score (0-100)
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
