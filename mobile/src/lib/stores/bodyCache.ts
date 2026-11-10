/**
 * In-memory stale-while-revalidate cache for the Heart rate and Weight screens: a page
 * renders straight from the last response and refreshes in the background, instead of
 * showing a skeleton for a round trip on every visit or day step. Per signed-in user:
 * api.clearUserCaches() empties it on sign-out / user switch.
 */
import type { HeartRateDay } from '$lib/types/heartRate';
import type { WeightPayload } from '$lib/types/weight';

type Entry<T> = { data: T; at: number };

const hrDays = new Map<string, Entry<HeartRateDay>>();
const HR_DAYS_MAX = 30;
let weight: Entry<WeightPayload> | null = null;

/** Past days barely change (a late sync), today fills in hourly. */
const PAST_DAY_FRESH_MS = 10 * 60_000;
const TODAY_FRESH_MS = 60_000;

export function cachedHeartRateDay(day: string): HeartRateDay | null {
  return hrDays.get(day)?.data ?? null;
}

export function heartRateDayIsFresh(day: string, today: string): boolean {
  const e = hrDays.get(day);
  if (!e) return false;
  return Date.now() - e.at < (day >= today ? TODAY_FRESH_MS : PAST_DAY_FRESH_MS);
}

const inflight = new Map<string, Promise<HeartRateDay | null>>();

/**
 * Fetch a day into the cache, sharing a request already in flight for it (a prefetch
 * of the previous day and the tap that opens it used to fetch it twice).
 */
export function loadHeartRateDay(
  day: string,
  fetcher: (day: string) => Promise<HeartRateDay | null>
): Promise<HeartRateDay | null> {
  const pending = inflight.get(day);
  if (pending) return pending;
  const p = fetcher(day)
    .then((res) => {
      if (res) storeHeartRateDay(day, res);
      return res;
    })
    .finally(() => inflight.delete(day));
  inflight.set(day, p);
  return p;
}

export function storeHeartRateDay(day: string, data: HeartRateDay): void {
  hrDays.delete(day);
  hrDays.set(day, { data, at: Date.now() });
  while (hrDays.size > HR_DAYS_MAX) hrDays.delete(hrDays.keys().next().value as string);
}

export function cachedWeight(): WeightPayload | null {
  return weight?.data ?? null;
}

export function storeWeight(data: WeightPayload): void {
  weight = { data, at: Date.now() };
}

export function clearBodyCache(): void {
  hrDays.clear();
  weight = null;
}
