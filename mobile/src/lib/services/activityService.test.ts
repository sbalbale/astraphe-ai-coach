import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getAuthHeadersMock = vi.fn(async () => ({}));
vi.mock('$lib/apiAuth', () => ({
  getAuthHeaders: (...args: unknown[]) => getAuthHeadersMock(...args)
}));

import {
  getActivityDetail,
  getActivityIntervals,
  getActivityLaps,
  getActivityStreams,
  getActivityZones,
  hydrateActivityStreams,
  refetchWorkoutFromStrava,
  streamsHaveHeartrate,
  streamsHaveVelocity
} from './activityService';

function res(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamsHaveVelocity', () => {
  it('false for null/missing/non-array stream', () => {
    expect(streamsHaveVelocity(null)).toBe(false);
    expect(streamsHaveVelocity({ time_series: {}, resolution_seconds: 1 })).toBe(false);
  });
  it('true when a positive finite value exists', () => {
    expect(
      streamsHaveVelocity({ time_series: { velocity_smooth: [0, NaN, 5] }, resolution_seconds: 1 })
    ).toBe(true);
  });
  it('false when all values are zero/non-finite', () => {
    expect(
      streamsHaveVelocity({ time_series: { velocity_smooth: [0, NaN] }, resolution_seconds: 1 })
    ).toBe(false);
  });
});

describe('streamsHaveHeartrate', () => {
  it('false for null/missing', () => {
    expect(streamsHaveHeartrate(null)).toBe(false);
  });
  it('true when a positive finite value exists', () => {
    expect(
      streamsHaveHeartrate({ time_series: { heartrate: [0, 145] }, resolution_seconds: 1 })
    ).toBe(true);
  });
});

describe('getActivityDetail', () => {
  it('returns normalized detail on success', async () => {
    fetchMock.mockResolvedValue(res({ streams: null, laps: null, intervals: null, zones: null }));
    const result = await getActivityDetail('w1');
    expect(result).toEqual({ streams: null, laps: [], intervals: null, zones: null });
  });

  it('throws with server-provided detail on failure', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'not found' }, false, 404));
    await expect(getActivityDetail('w1')).rejects.toThrow('not found');
  });

  it('throws with a fallback message when the error body has no detail', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, json: async () => { throw new Error('bad json'); } });
    await expect(getActivityDetail('w1')).rejects.toThrow('Failed to load workout detail (500)');
  });
});

describe('getActivityStreams (deprecated)', () => {
  it('returns null on 404', async () => {
    fetchMock.mockResolvedValue(res(null, false, 404));
    expect(await getActivityStreams('w1')).toBeNull();
  });
  it('returns data on success', async () => {
    fetchMock.mockResolvedValue(res({ time_series: {}, resolution_seconds: 1 }));
    expect(await getActivityStreams('w1')).toEqual({ time_series: {}, resolution_seconds: 1 });
  });
  it('throws on other errors', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'oops' }, false, 500));
    await expect(getActivityStreams('w1')).rejects.toThrow('oops');
  });
});

describe('getActivityLaps (deprecated)', () => {
  it('returns [] on 404', async () => {
    fetchMock.mockResolvedValue(res(null, false, 404));
    expect(await getActivityLaps('w1')).toEqual([]);
  });
  it('returns array on success', async () => {
    fetchMock.mockResolvedValue(res([{ lap_index: 1 }]));
    expect(await getActivityLaps('w1')).toEqual([{ lap_index: 1 }]);
  });
  it('returns [] when body is not an array', async () => {
    fetchMock.mockResolvedValue(res({ not: 'array' }));
    expect(await getActivityLaps('w1')).toEqual([]);
  });
  it('throws on other errors', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'oops' }, false, 500));
    await expect(getActivityLaps('w1')).rejects.toThrow('oops');
  });
});

describe('getActivityIntervals (deprecated)', () => {
  it('returns null on 404', async () => {
    fetchMock.mockResolvedValue(res(null, false, 404));
    expect(await getActivityIntervals('w1')).toBeNull();
  });
  it('returns data on success', async () => {
    fetchMock.mockResolvedValue(res({ intervals: [], source: 'laps', splits_metric: [], sport: 'row' }));
    const result = await getActivityIntervals('w1');
    expect(result?.sport).toBe('row');
  });
  it('throws on other errors', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'oops' }, false, 500));
    await expect(getActivityIntervals('w1')).rejects.toThrow('oops');
  });
});

describe('getActivityZones (deprecated)', () => {
  it('returns data on success', async () => {
    fetchMock.mockResolvedValue(res({ distribution: {}, zones: [], method: 'x', data_points: 0 }));
    const result = await getActivityZones('w1');
    expect(result?.method).toBe('x');
  });
  it('returns null on non-ok', async () => {
    fetchMock.mockResolvedValue(res(null, false, 500));
    expect(await getActivityZones('w1')).toBeNull();
  });
  it('returns null when fetch throws', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    expect(await getActivityZones('w1')).toBeNull();
  });
});

describe('refetchWorkoutFromStrava', () => {
  it('returns data on success', async () => {
    fetchMock.mockResolvedValue(
      res({
        status: 'ok',
        workout_id: 'w1',
        strava_activity_id: 1,
        stream_types: ['heartrate'],
        has_latlng_stream: false
      })
    );
    const result = await refetchWorkoutFromStrava('w1');
    expect(result.status).toBe('ok');
  });

  it('throws with server-provided detail on failure', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'rate limited' }, false, 429));
    await expect(refetchWorkoutFromStrava('w1')).rejects.toThrow('rate limited');
  });

  it('throws with a fallback message when the error body has no detail', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, json: async () => { throw new Error('bad json'); } });
    await expect(refetchWorkoutFromStrava('w1')).rejects.toThrow('Repull failed (500)');
  });
});

describe('hydrateActivityStreams', () => {
  it('returns data on success', async () => {
    fetchMock.mockResolvedValue(res({ status: 'ok', stream_types: ['heartrate'] }));
    const result = await hydrateActivityStreams('w1');
    expect(result.status).toBe('ok');
  });

  it('throws with server-provided detail on failure', async () => {
    fetchMock.mockResolvedValue(res({ detail: 'strava down' }, false, 502));
    await expect(hydrateActivityStreams('w1')).rejects.toThrow('strava down');
  });
});
