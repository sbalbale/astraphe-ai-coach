/**
 * The day picked on the Body tab (Recovery / Sleep / Strain). Each of those pages
 * keeps its own window state, so without this the pick resets to today whenever
 * you switch sub-tab. `null` means "today", so the tab follows the calendar
 * across midnight instead of pinning yesterday.
 */
export const bodyDate = $state<{ value: string | null }>({ value: null });

/** Remember the selected day (YYYY-MM-DD). Today or later is stored as null. */
export function rememberBodyDate(day: string, todayStr: string): void {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return;
  bodyDate.value = day >= todayStr ? null : day;
}

export function resetBodyDate(): void {
  bodyDate.value = null;
}
