import { describe, expect, it, vi, afterEach } from 'vitest';
import {
  cachedHeartRateDay,
  cachedWeight,
  clearBodyCache,
  heartRateDayIsFresh,
  storeHeartRateDay,
  storeWeight
} from './bodyCache';
import type { HeartRateDay } from '$lib/types/heartRate';
import type { WeightPayload } from '$lib/types/weight';

const day = (date: string) => ({ date }) as HeartRateDay;

afterEach(() => {
  clearBodyCache();
  vi.useRealTimers();
});

describe('bodyCache', () => {
  it('stores and returns heart-rate days', () => {
    storeHeartRateDay('2026-11-08', day('2026-11-08'));
    expect(cachedHeartRateDay('2026-11-08')?.date).toBe('2026-11-08');
    expect(cachedHeartRateDay('2026-11-07')).toBeNull();
  });

  it('treats today as stale sooner than a past day', () => {
    vi.useFakeTimers();
    storeHeartRateDay('2026-11-09', day('2026-11-09'));
    storeHeartRateDay('2026-11-08', day('2026-11-08'));
    vi.advanceTimersByTime(2 * 60_000);
    expect(heartRateDayIsFresh('2026-11-09', '2026-11-09')).toBe(false);
    expect(heartRateDayIsFresh('2026-11-08', '2026-11-09')).toBe(true);
    vi.advanceTimersByTime(10 * 60_000);
    expect(heartRateDayIsFresh('2026-11-08', '2026-11-09')).toBe(false);
  });

  it('keeps at most 30 days, dropping the oldest stored', () => {
    for (let i = 1; i <= 31; i++) storeHeartRateDay(`d${i}`, day(`d${i}`));
    expect(cachedHeartRateDay('d1')).toBeNull();
    expect(cachedHeartRateDay('d31')).not.toBeNull();
  });

  it('clears everything for a user switch', () => {
    storeHeartRateDay('2026-11-08', day('2026-11-08'));
    storeWeight({ entries: [] } as unknown as WeightPayload);
    clearBodyCache();
    expect(cachedHeartRateDay('2026-11-08')).toBeNull();
    expect(cachedWeight()).toBeNull();
  });
});

describe('loadHeartRateDay', () => {
  it('shares one request per day while it is in flight, then caches it', async () => {
    const { loadHeartRateDay } = await import('./bodyCache');
    let calls = 0;
    const fetcher = async (d: string) => {
      calls++;
      return { date: d } as HeartRateDay;
    };
    const [a, b] = await Promise.all([loadHeartRateDay('2026-11-08', fetcher), loadHeartRateDay('2026-11-08', fetcher)]);
    expect(calls).toBe(1);
    expect(a).toBe(b);
    expect(cachedHeartRateDay('2026-11-08')?.date).toBe('2026-11-08');
  });
});
