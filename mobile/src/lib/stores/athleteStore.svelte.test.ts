import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.mock() factories are hoisted above all top-level code, so any variables they
// reference must be created via vi.hoisted() to avoid a temporal-dead-zone error.
const authStoreMock = vi.hoisted(() => ({ user: { id: 'ath-1' } as { id: string } | null }));
vi.mock('./authStore.svelte', () => ({ authStore: authStoreMock }));

const apiMock = vi.hoisted(() => ({
  getAthleteState: vi.fn(),
  getAthleteProfile: vi.fn(),
  getSyncStatus: vi.fn(),
  getAthleteMetrics: vi.fn(),
  getBiometricsPage: vi.fn(),
  getPlan: vi.fn(),
  getCompletedWorkouts: vi.fn(),
  patchAthleteProfile: vi.fn(),
  deleteAthleteAccount: vi.fn(),
  deleteWorkout: vi.fn(),
  post: vi.fn(),
  updateWorkout: vi.fn(),
  unlinkIntegration: vi.fn()
}));
vi.mock('../api', () => ({ api: apiMock }));

import { athleteStore } from './athleteStore.svelte';

const CACHE_KEY = 'astraphe:athlete-cache:v2';

// The store's fetchAll() fires an unawaited updateProfile() call whenever the fetched
// profile's timezone_offset_min disagrees with the device's current offset -- match it
// by default so tests aren't surprised by that extra (unmocked-by-default) network call.
const CURRENT_TZ_OFFSET_MIN = -new Date().getTimezoneOffset();

function resolveAllTier1(overrides: Partial<Record<keyof typeof apiMock, unknown>> = {}) {
  apiMock.getAthleteState.mockResolvedValue(
    overrides.getAthleteState ?? { ctl: 50, atl: 40, tsb: 10, readiness_score: 70, hrv_rmssd: 55, sleep_hours: 7 }
  );
  apiMock.getAthleteProfile.mockResolvedValue(
    overrides.getAthleteProfile ?? { id: 'ath-1', timezone_offset_min: CURRENT_TZ_OFFSET_MIN }
  );
  apiMock.getSyncStatus.mockResolvedValue(overrides.getSyncStatus ?? { integrations: {} });
}

function resolveAllTier2(overrides: Partial<Record<keyof typeof apiMock, unknown>> = {}) {
  apiMock.getAthleteMetrics.mockResolvedValue(overrides.getAthleteMetrics ?? { ctl_trend: [] });
  apiMock.getBiometricsPage.mockResolvedValue(overrides.getBiometricsPage ?? { series: [], page: {} });
  apiMock.getPlan.mockResolvedValue(overrides.getPlan ?? { plan: [] });
  apiMock.getCompletedWorkouts.mockResolvedValue(overrides.getCompletedWorkouts ?? []);
}

beforeEach(() => {
  localStorage.clear();
  authStoreMock.user = { id: 'ath-1' };
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  // Safety net: fetchAll()'s fire-and-forget timezone-sync call hits this even when
  // a test's profile mock matches the current offset (e.g. background-refresh races),
  // so give it a harmless default rather than an unhandled-rejection-prone undefined.
  apiMock.patchAthleteProfile.mockResolvedValue({ ok: true, data: { status: 'success' } });
  athleteStore.reset();
  athleteStore.loading = false;
  // reset() clears initialLoadDone but not the private dedup flags; a fresh
  // fetchAll() in each test should still take the "full fetch" branch since
  // initialLoadDone is false after reset().
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('update / reset', () => {
  it('update only overwrites provided fields', () => {
    athleteStore.update({ ctl: 42 });
    expect(athleteStore.ctl).toBe(42);
    expect(athleteStore.atl).toBe(0);
  });

  it('reset clears state and the localStorage cache', () => {
    athleteStore.update({ ctl: 42 });
    athleteStore.profile = { id: 'x' };
    localStorage.setItem(CACHE_KEY, '{}');
    athleteStore.reset();
    expect(athleteStore.ctl).toBe(0);
    expect(athleteStore.profile).toBeNull();
    expect(localStorage.getItem(CACHE_KEY)).toBeNull();
  });
});

describe('fetchAll (full fetch path)', () => {
  it('populates tier-1 fields and completes tier-2 in the background', async () => {
    resolveAllTier1();
    const today = new Date().toISOString().slice(0, 10);
    resolveAllTier2({
      getBiometricsPage: {
        series: [
          {
            date: today,
            readiness_score: 80,
            recovery_score: 80,
            hrv_rmssd: 60,
            sleep_duration_min: 420
          }
        ],
        page: {}
      }
    });
    await athleteStore.fetchAll();
    expect(athleteStore.ctl).toBe(50);
    expect(athleteStore.initialLoadDone).toBe(true);
    expect(athleteStore.loading).toBe(false);

    await vi.waitFor(() => expect(athleteStore.metrics).toEqual({ ctl_trend: [] }));
    expect(athleteStore.readiness).toBe(80);
    expect(athleteStore.plan).toEqual({ plan: [] });
  });

  it('is a no-op re-entrant call while already loading', async () => {
    let resolveState: (v: unknown) => void;
    apiMock.getAthleteState.mockReturnValue(
      new Promise((resolve) => {
        resolveState = resolve;
      })
    );
    apiMock.getAthleteProfile.mockResolvedValue(null);
    apiMock.getSyncStatus.mockResolvedValue(null);
    resolveAllTier2();

    const first = athleteStore.fetchAll();
    const second = athleteStore.fetchAll(); // should return immediately (this.loading is true)
    await second;
    resolveState!({ ctl: 1, atl: 1, tsb: 1 });
    await first;
    expect(athleteStore.ctl).toBe(1);
  });

  it('handles partial API failures via Promise.allSettled without throwing', async () => {
    apiMock.getAthleteState.mockRejectedValue(new Error('state failed'));
    apiMock.getAthleteProfile.mockResolvedValue({ id: 'ath-1' });
    apiMock.getSyncStatus.mockResolvedValue(null);
    resolveAllTier2();
    await athleteStore.fetchAll();
    expect(athleteStore.ctl).toBe(0); // state never applied
    expect(athleteStore.profile).toEqual({ id: 'ath-1' });
    expect(athleteStore.initialLoadDone).toBe(true);
  });

  it('swallows an unexpected error and still marks the load done', async () => {
    apiMock.getAthleteState.mockImplementation(() => {
      throw new Error('synchronous throw');
    });
    apiMock.getAthleteProfile.mockResolvedValue(null);
    apiMock.getSyncStatus.mockResolvedValue(null);
    await athleteStore.fetchAll();
    expect(athleteStore.loading).toBe(false);
    expect(athleteStore.initialLoadDone).toBe(true);
  });
});

describe('fetchAll (cache hydration + SWR background refresh)', () => {
  it('hydrates synchronously from a fresh cache entry for the current athlete', async () => {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        athleteId: 'ath-1',
        savedAt: Date.now(),
        ctl: 77,
        atl: 0,
        tsb: 0,
        readiness: 0,
        hrv: 0,
        sleep: 0,
        recent_tss: 0,
        days_on_platform: 0,
        profile: { id: 'ath-1' },
        syncStatus: null,
        metrics: null,
        biometrics: null,
        plan: null,
        workouts: []
      })
    );
    // Background refresh triggers because staleness > 60s (never refreshed yet);
    // resolve it harmlessly.
    resolveAllTier1();
    resolveAllTier2();
    await athleteStore.fetchAll();
    expect(athleteStore.ctl).toBe(77);
    expect(athleteStore.initialLoadDone).toBe(true);
  });

  it('ignores a cache entry for a different athlete', async () => {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ athleteId: 'other-athlete', savedAt: Date.now(), ctl: 999 })
    );
    resolveAllTier1();
    resolveAllTier2();
    await athleteStore.fetchAll();
    expect(athleteStore.ctl).toBe(50); // came from the network fetch, not the mismatched cache
  });

  it('ignores an expired cache entry', async () => {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ athleteId: 'ath-1', savedAt: Date.now() - 25 * 60 * 60 * 1000, ctl: 999 })
    );
    resolveAllTier1();
    resolveAllTier2();
    await athleteStore.fetchAll();
    expect(athleteStore.ctl).toBe(50);
  });

  it('force=true bypasses the SWR background path and does a full fetch', async () => {
    resolveAllTier1();
    resolveAllTier2();
    await athleteStore.fetchAll(); // establishes initialLoadDone
    apiMock.getAthleteState.mockClear();
    resolveAllTier1({ getAthleteState: { ctl: 61, atl: 1, tsb: 1 } });
    await athleteStore.fetchAll(true);
    expect(apiMock.getAthleteState).toHaveBeenCalled();
    expect(athleteStore.ctl).toBe(61);
  });
});

describe('loadMoreBiometrics', () => {
  it('returns false when there is no more data', async () => {
    athleteStore.biometrics = { series: [], page: { has_more: false } };
    expect(await athleteStore.loadMoreBiometrics()).toBe(false);
  });

  it('merges the next page into the existing series', async () => {
    athleteStore.biometrics = {
      series: [{ date: '2026-05-20' }],
      page: { has_more: true, next_before: '2026-05-19' },
      hrvData: [],
      sleepData: [],
      sleepScores: []
    };
    apiMock.getBiometricsPage.mockResolvedValue({
      series: [{ date: '2026-05-19' }],
      page: { has_more: false },
      hrvData: [],
      sleepData: [],
      sleepScores: []
    });
    const result = await athleteStore.loadMoreBiometrics();
    expect(result).toBe(true);
    expect(athleteStore.biometrics.series).toHaveLength(2);
  });

  it('returns false when the next page has no series', async () => {
    athleteStore.biometrics = { series: [], page: { has_more: true, next_before: 'x' } };
    apiMock.getBiometricsPage.mockResolvedValue({ series: [] });
    expect(await athleteStore.loadMoreBiometrics()).toBe(false);
  });

  it('returns false and logs on a fetch error', async () => {
    athleteStore.biometrics = { series: [], page: { has_more: true, next_before: 'x' } };
    apiMock.getBiometricsPage.mockRejectedValue(new Error('boom'));
    expect(await athleteStore.loadMoreBiometrics()).toBe(false);
  });

  it('short-circuits when already loading more', async () => {
    athleteStore.biometricsLoadingMore = true;
    expect(await athleteStore.loadMoreBiometrics()).toBe(false);
    expect(apiMock.getBiometricsPage).not.toHaveBeenCalled();
  });
});

describe('updateProfile', () => {
  it('records the error and returns false on failure', async () => {
    apiMock.patchAthleteProfile.mockResolvedValue({ ok: false, error: 'Invalid FTP' });
    const result = await athleteStore.updateProfile({ ftp_watts: -1 });
    expect(result).toBe(false);
    expect(athleteStore.lastProfileSaveError).toBe('Invalid FTP');
  });

  it('refetches the profile and persists cache on success', async () => {
    apiMock.patchAthleteProfile.mockResolvedValue({ ok: true, data: { status: 'success' } });
    apiMock.getAthleteProfile.mockResolvedValue({ id: 'ath-1', display_name: 'Sean' });
    const result = await athleteStore.updateProfile({ display_name: 'Sean' });
    expect(result).toBe(true);
    expect(athleteStore.profile).toEqual({ id: 'ath-1', display_name: 'Sean' });
  });

  it('returns false when the save succeeds but the server reports non-success status', async () => {
    apiMock.patchAthleteProfile.mockResolvedValue({ ok: true, data: { status: 'pending' } });
    const result = await athleteStore.updateProfile({});
    expect(result).toBe(false);
    expect(athleteStore.lastProfileSaveError).toContain('Failed to save');
  });
});

describe('deleteAccount', () => {
  it('true on success status', async () => {
    apiMock.deleteAthleteAccount.mockResolvedValue({ status: 'success' });
    expect(await athleteStore.deleteAccount()).toBe(true);
  });
  it('false otherwise', async () => {
    apiMock.deleteAthleteAccount.mockResolvedValue(null);
    // `res && res.status === 'success'` short-circuits to the falsy `res` itself (null),
    // not a coerced boolean -- assert falsy rather than strict `false`.
    expect(await athleteStore.deleteAccount()).toBeFalsy();
  });
});

describe('deleteWorkout', () => {
  it('removes the workout locally and persists cache on success', async () => {
    athleteStore.workouts = [{ id: 'w1' }, { id: 'w2' }];
    apiMock.deleteWorkout.mockResolvedValue({ status: 'success' });
    const result = await athleteStore.deleteWorkout('w1');
    expect(result).toBe(true);
    expect(athleteStore.workouts.map((w: any) => w.id)).toEqual(['w2']);
  });

  it('returns false without mutating state on failure', async () => {
    athleteStore.workouts = [{ id: 'w1' }];
    apiMock.deleteWorkout.mockResolvedValue(null);
    const result = await athleteStore.deleteWorkout('w1');
    expect(result).toBe(false);
    expect(athleteStore.workouts).toHaveLength(1);
  });
});

describe('addWorkout / updateWorkout / addSleep', () => {
  it('addWorkout posts and refetches on success', async () => {
    apiMock.post.mockResolvedValue({ id: 'new' });
    resolveAllTier1();
    resolveAllTier2();
    const result = await athleteStore.addWorkout({ sport: 'run' });
    expect(result).toBe(true);
  });

  it('addWorkout returns false without refetching when the post fails', async () => {
    apiMock.post.mockResolvedValue(null);
    const result = await athleteStore.addWorkout({ sport: 'run' });
    expect(result).toBe(false);
    expect(apiMock.getAthleteState).not.toHaveBeenCalled();
  });

  it('updateWorkout returns the updated workout on success', async () => {
    apiMock.updateWorkout.mockResolvedValue({ status: 'success', workout: { id: 'w1' } });
    resolveAllTier1();
    resolveAllTier2();
    const result = await athleteStore.updateWorkout('w1', { title: 'x' });
    expect(result).toEqual({ id: 'w1' });
  });

  it('updateWorkout returns true when the server omits the workout payload', async () => {
    apiMock.updateWorkout.mockResolvedValue({ status: 'success' });
    resolveAllTier1();
    resolveAllTier2();
    const result = await athleteStore.updateWorkout('w1', { title: 'x' });
    expect(result).toBe(true);
  });

  it('updateWorkout returns false on failure', async () => {
    apiMock.updateWorkout.mockResolvedValue({ status: 'error' });
    const result = await athleteStore.updateWorkout('w1', {});
    expect(result).toBe(false);
  });

  it('addSleep posts and refetches on success', async () => {
    apiMock.post.mockResolvedValue({ ok: true });
    resolveAllTier1();
    resolveAllTier2();
    const result = await athleteStore.addSleep({ date: '2026-05-20' });
    expect(result).toBe(true);
  });

  it('addSleep returns false when the post fails', async () => {
    apiMock.post.mockResolvedValue(null);
    const result = await athleteStore.addSleep({});
    expect(result).toBe(false);
  });
});

describe('unlinkIntegration', () => {
  it('refreshes sync status on success', async () => {
    apiMock.unlinkIntegration.mockResolvedValue({ status: 'success' });
    apiMock.getSyncStatus.mockResolvedValue({ integrations: { strava: { connected: false } } });
    const result = await athleteStore.unlinkIntegration('strava');
    expect(result).toBe(true);
    expect(athleteStore.syncStatus).toEqual({ integrations: { strava: { connected: false } } });
  });

  it('returns false on failure', async () => {
    apiMock.unlinkIntegration.mockResolvedValue(null);
    const result = await athleteStore.unlinkIntegration('strava');
    expect(result).toBe(false);
  });
});
