import { format } from 'date-fns';

/**
 * The device-local calendar day (YYYY-MM-DD) of a timestamp. `started_at.slice(0, 10)`
 * is the *UTC* day, so an evening workout west of UTC landed on the next day.
 * Plain dates ("2026-11-02") are returned unchanged.
 */
export function localDay(value: unknown): string {
  if (typeof value !== 'string' || !value) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : format(d, 'yyyy-MM-dd');
}
