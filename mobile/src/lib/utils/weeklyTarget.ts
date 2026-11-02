/**
 * Weekly TSS target derived from the athlete's own training history.
 *
 * CTL is the exponentially weighted *daily* TSS average over ~42 days, so
 * `CTL * 7` is the weekly load that merely maintains current fitness. A build
 * week asks for a little more than that, so the target is maintenance plus a
 * small progression step, rounded to the nearest 5 TSS.
 */
export const WEEKLY_PROGRESSION = 1.05;

/** Below this CTL there is not enough history for a meaningful target. */
const MIN_CTL = 5;

export function weeklyTssTarget(ctl: number | null | undefined, stored?: number | null): number | null {
  const c = Number(ctl);
  if (Number.isFinite(c) && c >= MIN_CTL) {
    return Math.round((c * 7 * WEEKLY_PROGRESSION) / 5) * 5;
  }
  const s = Number(stored);
  return Number.isFinite(s) && s > 0 ? Math.round(s) : null;
}
