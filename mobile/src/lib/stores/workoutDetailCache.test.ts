import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// SvelteKit's $app/environment reports `browser: false` under vitest (it's not an
// actual browser build target), but every function in this module short-circuits
// to a no-op when !browser -- force it true so the real cache logic runs.
vi.mock('$app/environment', () => ({ browser: true }));

const getActivityDetailMock = vi.fn();
vi.mock('../services/activityService', () => ({
  getActivityDetail: (...args: unknown[]) => getActivityDetailMock(...args)
}));

import {
  clearAllWorkoutDetailCache,
  clearWorkoutDetailFromCache,
  loadWorkoutDetailCache,
  preloadWorkoutDetail,
  saveWorkoutDetailToCache
} from './workoutDetailCache';

const CACHE_KEY = 'astraphe:workout-detail:v2';

function sampleData() {
  return { streams: null, laps: [], intervals: null, zones: null };
}

beforeEach(() => {
  localStorage.clear();
  getActivityDetailMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('loadWorkoutDetailCache', () => {
  it('empty object when nothing stored', () => {
    expect(loadWorkoutDetailCache()).toEqual({});
  });

  it('returns stored entries', () => {
    saveWorkoutDetailToCache('w1', sampleData());
    const cache = loadWorkoutDetailCache();
    expect(cache.w1).toBeDefined();
  });

  it('drops expired entries and persists the cleanup', () => {
    const stale = { savedAt: Date.now() - 8 * 24 * 60 * 60 * 1000, ...sampleData() };
    localStorage.setItem(CACHE_KEY, JSON.stringify({ w1: stale }));
    const cache = loadWorkoutDetailCache();
    expect(cache.w1).toBeUndefined();
    // cleanup was persisted
    const raw = JSON.parse(localStorage.getItem(CACHE_KEY)!);
    expect(raw.w1).toBeUndefined();
  });

  it('returns {} when stored JSON is corrupt', () => {
    localStorage.setItem(CACHE_KEY, 'not json{{{');
    expect(loadWorkoutDetailCache()).toEqual({});
  });
});

describe('saveWorkoutDetailToCache', () => {
  it('stores the entry with a savedAt timestamp', () => {
    saveWorkoutDetailToCache('w1', sampleData());
    const cache = loadWorkoutDetailCache();
    expect(cache.w1.savedAt).toBeTypeOf('number');
    expect(cache.w1.laps).toEqual([]);
  });

  it('evicts the oldest entries beyond MAX_ENTRIES (20)', () => {
    // Ascending-but-recent timestamps (well within the 7-day TTL) so the eviction
    // exercised here is the MAX_ENTRIES LRU path, not the expired-entry cleanup path.
    const now = Date.now();
    for (let i = 0; i < 25; i++) {
      const entry = { savedAt: now - (25 - i) * 1000, ...sampleData() };
      const raw = JSON.parse(localStorage.getItem(CACHE_KEY) || '{}');
      raw[`w${i}`] = entry;
      localStorage.setItem(CACHE_KEY, JSON.stringify(raw));
    }
    saveWorkoutDetailToCache('w25', sampleData());
    const cache = loadWorkoutDetailCache();
    expect(Object.keys(cache).length).toBeLessThanOrEqual(20);
    // the newest entry should have survived eviction
    expect(cache.w25).toBeDefined();
    // one of the oldest (w0) should have been evicted
    expect(cache.w0).toBeUndefined();
  });

  it('evicts the oldest half and retries when quota is exceeded', () => {
    saveWorkoutDetailToCache('w1', sampleData());
    saveWorkoutDetailToCache('w2', sampleData());
    const setItemSpy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementationOnce(() => {
        const err = new Error('quota');
        err.name = 'QuotaExceededError';
        throw err;
      })
      .mockImplementationOnce((key, value) => {
        // second attempt (after eviction) succeeds via the real implementation
        Storage.prototype.setItem.call(localStorage, key, value);
      });
    expect(() => saveWorkoutDetailToCache('w3', sampleData())).not.toThrow();
    setItemSpy.mockRestore();
  });

  it('gives up silently when the retry also throws', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      const err = new Error('quota');
      err.name = 'QuotaExceededError';
      throw err;
    });
    expect(() => saveWorkoutDetailToCache('w1', sampleData())).not.toThrow();
    setItemSpy.mockRestore();
  });

  it('non-quota errors are swallowed without a retry', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('some other storage error');
    });
    expect(() => saveWorkoutDetailToCache('w1', sampleData())).not.toThrow();
    setItemSpy.mockRestore();
  });
});

describe('clearWorkoutDetailFromCache', () => {
  it('removes a specific entry', () => {
    saveWorkoutDetailToCache('w1', sampleData());
    saveWorkoutDetailToCache('w2', sampleData());
    clearWorkoutDetailFromCache('w1');
    const cache = loadWorkoutDetailCache();
    expect(cache.w1).toBeUndefined();
    expect(cache.w2).toBeDefined();
  });

  it('is a no-op when the entry does not exist', () => {
    expect(() => clearWorkoutDetailFromCache('missing')).not.toThrow();
  });
});

describe('clearAllWorkoutDetailCache', () => {
  it('removes the whole cache key', () => {
    saveWorkoutDetailToCache('w1', sampleData());
    clearAllWorkoutDetailCache();
    expect(localStorage.getItem(CACHE_KEY)).toBeNull();
  });
});

describe('preloadWorkoutDetail', () => {
  it('no-ops for an empty workoutId', async () => {
    await preloadWorkoutDetail('');
    expect(getActivityDetailMock).not.toHaveBeenCalled();
  });

  it('fetches and caches when not already cached', async () => {
    getActivityDetailMock.mockResolvedValue({
      streams: null,
      laps: [{ lap_index: 1 }],
      intervals: null,
      zones: null
    });
    await preloadWorkoutDetail('w1');
    expect(getActivityDetailMock).toHaveBeenCalledWith('w1');
    const cache = loadWorkoutDetailCache();
    expect(cache.w1.laps).toEqual([{ lap_index: 1 }]);
  });

  it('defaults laps to [] when the response omits them', async () => {
    getActivityDetailMock.mockResolvedValue({ streams: null, laps: undefined, intervals: null, zones: null });
    await preloadWorkoutDetail('w2');
    const cache = loadWorkoutDetailCache();
    expect(cache.w2.laps).toEqual([]);
  });

  it('skips fetching when already cached', async () => {
    saveWorkoutDetailToCache('w1', sampleData());
    await preloadWorkoutDetail('w1');
    expect(getActivityDetailMock).not.toHaveBeenCalled();
  });

  it('swallows a fetch failure', async () => {
    getActivityDetailMock.mockRejectedValue(new Error('network down'));
    await expect(preloadWorkoutDetail('w3')).resolves.toBeUndefined();
  });

  it('deduplicates concurrent preloads for the same workoutId', async () => {
    let resolveFn: (v: unknown) => void;
    getActivityDetailMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      })
    );
    const p1 = preloadWorkoutDetail('w4');
    const p2 = preloadWorkoutDetail('w4');
    resolveFn!({ streams: null, laps: [], intervals: null, zones: null });
    await Promise.all([p1, p2]);
    expect(getActivityDetailMock).toHaveBeenCalledTimes(1);
  });
});
