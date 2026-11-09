/**
 * Sleep need, split into the parts the backend adds up (`compute_sleep_need` in
 * backend/app/services/algorithms.py): an 8 h baseline, extra for the previous day's
 * strain (100 strain = +2 h), and 80% of the previous night's unpaid debt (max 2 h).
 */
export const BASELINE_SLEEP_MIN = 480;
const MAX_STRAIN_TAX_MIN = 120;
const MAX_DEBT_MIN = 120;
const DEBT_DECAY = 0.8;

type Row = { sleep_need_min?: unknown; sleep_debt_min?: unknown; strain_score?: unknown } | null | undefined;

export type SleepNeedParts = { total: number; baseline: number; strain: number; debt: number };

const num = (v: unknown): number | null => {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function carriedDebt(debtMin: unknown): number {
  return Math.round(clamp((num(debtMin) ?? 0) * DEBT_DECAY, 0, MAX_DEBT_MIN));
}

function strainTax(strain: unknown): number {
  return Math.round((clamp(num(strain) ?? 0, 0, 100) / 100) * MAX_STRAIN_TAX_MIN);
}

/**
 * The stored need for the night ending on `row`'s date, with its parts. `prev` is the
 * day before (its debt carries over). Strain is what remains, so the parts add up to the
 * stored total. Null when the night has no stored need.
 */
export function sleepNeedParts(row: Row, prev: Row): SleepNeedParts | null {
  const total = num(row?.sleep_need_min);
  if (total == null || total <= 0) return null;
  const debt = Math.min(carriedDebt(prev?.sleep_debt_min), Math.max(0, total - BASELINE_SLEEP_MIN));
  const strain = Math.max(0, total - BASELINE_SLEEP_MIN - debt);
  return { total, baseline: BASELINE_SLEEP_MIN, strain, debt };
}

/**
 * Tonight's need from today's row: today's strain so far plus the debt left after last
 * night. Null until last night's debt is known.
 */
export function tonightSleepNeed(today: Row): SleepNeedParts | null {
  if (num(today?.sleep_debt_min) == null) return null;
  const strain = strainTax(today?.strain_score);
  const debt = carriedDebt(today?.sleep_debt_min);
  return { total: BASELINE_SLEEP_MIN + strain + debt, baseline: BASELINE_SLEEP_MIN, strain, debt };
}
