import { api } from '../api';
import { authStore } from './authStore.svelte';
import {
  calculateSleepScore,
  calculateRecoveryScore,
  currentRecoveryState,
  firstPositiveFiniteNumber
} from '../utils/biometrics';

const CACHE_KEY = 'astraphe:athlete-cache:v2';
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

type CachePayload = {
  athleteId: string;
  savedAt: number;
  ctl: number;
  atl: number;
  tsb: number;
  readiness: number;
  hrv: number;
  sleep: number;
  recent_tss: number;
  days_on_platform: number;
  profile: any;
  syncStatus: any;
  metrics: any;
  biometrics: any;
  plan: any;
  workouts: any[];
};

function loadCache(athleteId: string | null): CachePayload | null {
  if (typeof localStorage === 'undefined' || !athleteId) return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachePayload;
    if (parsed.athleteId !== athleteId) return null;
    if (Date.now() - parsed.savedAt > CACHE_TTL_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveCache(payload: CachePayload): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  } catch {
    // QuotaExceededError or serialization failure — degrade silently.
  }
}

function clearCache(): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(CACHE_KEY);
  } catch {
    // ignore
  }
}

type Settled<F extends (...a: any[]) => Promise<unknown>> = PromiseSettledResult<Awaited<ReturnType<F>>>;
/** Tier 2 requests in flight, and the profile-write count when they started. */
type Tier2Request = {
  profileWrites: number;
  results: Promise<
    [
      Settled<typeof api.getAthleteMetrics>,
      Settled<typeof api.getBiometricsPage>,
      Settled<typeof api.getPlan>,
      Settled<typeof api.getCompletedWorkouts>
    ]
  >;
};

export class AthleteState {
  ctl = $state(0);
  atl = $state(0);
  tsb = $state(0);
  readiness = $state(0);
  hrv = $state(0);
  sleep = $state(0);
  recent_tss = $state(0);
  days_on_platform = $state(0);

  // New datasets
  metrics = $state<any>(null);
  biometrics = $state<any>(null);
  plan = $state<any>(null);
  profile = $state<any>(null);
  workouts = $state<any[]>([]);
  syncStatus = $state<any>(null);
  loading = $state(false);
  initialLoadDone = $state(false);
  biometricsLoadingMore = $state(false);
  /** True once every older workout has been loaded (see ensureWorkoutsFrom). */
  workoutsComplete = $state(false);
  private _workoutsLoadingMore: Promise<void> | null = null;
  lastProfileSaveError = $state<string | null>(null);

  // Non-reactive dedup flag so two simultaneous fetchAll() calls don't trigger
  // duplicate background refreshes (layout effect + dashboard onMount fire in quick succession).
  private _refreshing = false;
  private _lastRefreshAt = 0; // timestamp of last completed background refresh
  // Bumped by reset() (sign-out / user switch). Every async step captures it and drops
  // its result if it changed, so a slow response for the previous user can never land
  // in the store (or the cache) after someone else signs in on the same device.
  private _gen = 0;
  // A forced refresh requested while a load was running (e.g. after adding a workout).
  private _forceQueued = false;
  // Bumped by every profile save. A refresh that started before a save must not
  // overwrite what the save just stored (a just-saved weight appeared to revert).
  private _profileWrites = 0;

  /** True when the store still belongs to the run that captured `gen`. */
  private current(gen: number): boolean {
    return gen === this._gen;
  }

  update(data: Partial<AthleteState>) {
    if (data.ctl !== undefined) this.ctl = data.ctl;
    if (data.atl !== undefined) this.atl = data.atl;
    if (data.tsb !== undefined) this.tsb = data.tsb;
    if (data.readiness !== undefined) this.readiness = data.readiness;
    if (data.hrv !== undefined) this.hrv = data.hrv;
    if (data.sleep !== undefined) this.sleep = data.sleep;
    if (data.recent_tss !== undefined) this.recent_tss = data.recent_tss;
    if (data.days_on_platform !== undefined) this.days_on_platform = data.days_on_platform;
  }

  reset() {
    this._gen++;
    this.loading = false;
    this._refreshing = false;
    this._lastRefreshAt = 0;
    this._forceQueued = false;
    this.biometricsLoadingMore = false;
    this.lastProfileSaveError = null;
    this.ctl = 0;
    this.atl = 0;
    this.tsb = 0;
    this.readiness = 0;
    this.hrv = 0;
    this.sleep = 0;
    this.recent_tss = 0;
    this.days_on_platform = 0;
    this.metrics = null;
    this.biometrics = null;
    this.plan = null;
    this.profile = null;
    this.workouts = [];
    this.workoutsComplete = false;
    this.syncStatus = null;
    this.initialLoadDone = false;
    clearCache();
  }

  private hydrateFromCache(athleteId: string | null): boolean {
    if (this.initialLoadDone) return false;
    const cached = loadCache(athleteId);
    if (!cached) return false;

    this.update({
      ctl: cached.ctl ?? 0,
      atl: cached.atl ?? 0,
      tsb: cached.tsb ?? 0,
      readiness: cached.readiness ?? 0,
      hrv: cached.hrv ?? 0,
      sleep: cached.sleep ?? 0,
      recent_tss: cached.recent_tss ?? 0,
      days_on_platform: cached.days_on_platform ?? 0,
    });
    if (cached.profile) this.profile = cached.profile;
    if (cached.syncStatus) this.syncStatus = cached.syncStatus;
    if (cached.metrics) this.metrics = cached.metrics;
    if (cached.biometrics) this.biometrics = cached.biometrics;
    if (cached.plan) this.plan = cached.plan;
    if (Array.isArray(cached.workouts)) this.workouts = cached.workouts;

    this.initialLoadDone = true;
    console.log('[AthleteStore] Hydrated from cache (age=' + Math.round((Date.now() - cached.savedAt) / 1000) + 's)');
    return true;
  }

  private persistCurrent(athleteId: string): void {
    // Never write a cache for anyone but the signed-in user.
    if (!athleteId || authStore.user?.id !== athleteId) return;
    saveCache({
      athleteId,
      savedAt: Date.now(),
      ctl: this.ctl,
      atl: this.atl,
      tsb: this.tsb,
      readiness: this.readiness,
      hrv: this.hrv,
      sleep: this.sleep,
      recent_tss: this.recent_tss,
      days_on_platform: this.days_on_platform,
      profile: this.profile,
      syncStatus: this.syncStatus,
      metrics: this.metrics,
      biometrics: this.biometrics,
      plan: this.plan,
      workouts: this.workouts,
    });
  }

  /** The profile request failed: try again shortly (twice), so the app doesn't treat the
   * account as not set up because of one failed request. */
  private retryProfile(gen: number, attempt = 1): void {
    if (attempt > 2) return;
    setTimeout(async () => {
      if (!this.current(gen) || this.profile) return;
      const profileWritesAtStart = this._profileWrites;
      const p = await api.getAthleteProfile().catch(() => null);
      if (!this.current(gen)) return;
      if (p && profileWritesAtStart === this._profileWrites) this.profile = p;
      else if (!p) this.retryProfile(gen, attempt + 1);
    }, attempt === 1 ? 1500 : 5000);
  }

  async fetchAll(force = false) {
    if (this.loading) {
      // Don't drop a forced refresh (new workout/sleep) just because a load is running.
      if (force) this._forceQueued = true;
      return;
    }

    const athleteId = authStore.user?.id ?? null;
    const gen = this._gen;

    // 1. Hydrate synchronously from cache so the dashboard can render immediately.
    this.hydrateFromCache(athleteId);

    // 2. If we already have data (cache hit or previous fetch) and caller didn't force,
    //    refresh in background without blocking. This is the SWR path.
    if (this.initialLoadDone && !force) {
      const staleness = Date.now() - this._lastRefreshAt;
      if (!this._refreshing && staleness > 60_000) void this.refreshInBackground(athleteId);
      return;
    }

    // 3. Full fetch path: we have no usable data, or caller forced a refresh.
    console.log('[AthleteStore] Starting fetchAll (network)');
    this.loading = true;

    try {
      const profileWritesAtStart = this._profileWrites;
      // Tier 2 is requested now, alongside tier 1, and applied once tier 1 is in (it
      // only uses tier 1's state as a fallback): it used to wait a full round trip.
      const tier2 = this.requestTier2();
      const [stateResult, profileResult, syncResult] = await Promise.allSettled([
        api.getAthleteState(),
        api.getAthleteProfile(),
        api.getSyncStatus()
      ]);

      if (!this.current(gen)) return;
      const state = stateResult.status === 'fulfilled' ? stateResult.value : null;
      const profileData = profileResult.status === 'fulfilled' ? profileResult.value : null;
      const syncData = syncResult.status === 'fulfilled' ? syncResult.value : null;

      if (state) {
        this.update({
          ctl: state.ctl, atl: state.atl, tsb: state.tsb,
          readiness: state.readiness_score || state.readiness,
          hrv: state.hrv_rmssd || state.hrv,
          sleep: state.sleep_hours || state.sleep,
          recent_tss: state.recent_tss || 0,
          days_on_platform: state.days_on_platform || 0
        });
      }
      if (profileData && profileWritesAtStart === this._profileWrites) this.profile = profileData;
      if (syncData) this.syncStatus = syncData;
      if (!profileData) this.retryProfile(gen);

      this.initialLoadDone = true;
      this.loading = false;
      // A full fetch is also a refresh: without this, the next fetchAll() saw
      // staleness ≈ now and immediately refetched all seven endpoints.
      this._lastRefreshAt = Date.now();

      console.log('[AthleteStore] Tier 1 complete — dashboard ready');

      const currentOffset = -new Date().getTimezoneOffset();
      if (this.profile && this.profile.timezone_offset_min !== currentOffset) {
        console.log(`[AthleteStore] Updating timezone offset: ${this.profile.timezone_offset_min} -> ${currentOffset}`);
        this.updateProfile({ timezone_offset_min: currentOffset });
      }

      // Tier 2 background enrichment + persist cache on completion.
      this.loadTier2(athleteId, state, gen, tier2);

      if (this._forceQueued) {
        this._forceQueued = false;
        void this.fetchAll(true);
      }
    } catch (e) {
      console.error('[AthleteStore] Error in fetchAll:', e);
      if (!this.current(gen)) return;
      this.loading = false;
      this.initialLoadDone = true;
    }
  }

  private async refreshInBackground(athleteId: string | null) {
    // Refresh both tiers silently. Does NOT touch `loading` so the UI keeps showing cached data.
    if (this._refreshing) return;
    this._refreshing = true;
    const gen = this._gen;
    try {
      const profileWritesAtStart = this._profileWrites;
      // Tier 2 is requested now, alongside tier 1, and applied once tier 1 is in (it
      // only uses tier 1's state as a fallback): it used to wait a full round trip.
      const tier2 = this.requestTier2();
      const [stateResult, profileResult, syncResult] = await Promise.allSettled([
        api.getAthleteState(),
        api.getAthleteProfile(),
        api.getSyncStatus()
      ]);

      if (!this.current(gen)) return;
      const state = stateResult.status === 'fulfilled' ? stateResult.value : null;
      const profileData = profileResult.status === 'fulfilled' ? profileResult.value : null;
      const syncData = syncResult.status === 'fulfilled' ? syncResult.value : null;

      if (state) {
        this.update({
          ctl: state.ctl, atl: state.atl, tsb: state.tsb,
          readiness: state.readiness_score || state.readiness,
          hrv: state.hrv_rmssd || state.hrv,
          sleep: state.sleep_hours || state.sleep,
          recent_tss: state.recent_tss || 0,
          days_on_platform: state.days_on_platform || 0
        });
      }
      if (profileData && profileWritesAtStart === this._profileWrites) this.profile = profileData;
      if (syncData) this.syncStatus = syncData;

      this.loadTier2(athleteId, state, gen, tier2);
    } catch (e) {
      console.error('[AthleteStore] Background refresh error:', e);
    } finally {
      if (this.current(gen)) {
        this._refreshing = false;
        this._lastRefreshAt = Date.now();
      }
    }
  }

  /** Start the tier 2 requests (and note the profile-write count they started at). */
  private requestTier2(): Tier2Request {
    return {
      profileWrites: this._profileWrites,
      results: Promise.allSettled([
        api.getAthleteMetrics(),
        api.getBiometricsPage({ limit: 60 }),
        api.getPlan(),
        api.getCompletedWorkouts(200)
      ])
    };
  }

  private loadTier2(
    athleteId: string | null,
    state: any,
    gen: number = this._gen,
    tier2: Tier2Request = this.requestTier2()
  ) {
    const profileWritesAtStart = tier2.profileWrites;
    tier2.results.then(([metricsResult, bioResult, planResult, workoutsResult]) => {
      if (!this.current(gen)) return;
      const metricsData = metricsResult.status === 'fulfilled' ? metricsResult.value : null;
      const biometricsData = bioResult.status === 'fulfilled' ? bioResult.value : null;
      const planData = planResult.status === 'fulfilled' ? planResult.value : null;
      const workoutsData = workoutsResult.status === 'fulfilled' ? workoutsResult.value : null;

      if (metricsData) this.metrics = metricsData;
      // A weight save reloads biometrics itself; don't let this older response undo it.
      if (biometricsData && profileWritesAtStart === this._profileWrites) {
        this.biometrics = biometricsData;
        if (this.biometrics?.series?.length > 0) {
          const { row } = currentRecoveryState(
            this.biometrics.series,
            this.profile?.timezone_offset_min
          );
          this.readiness =
            firstPositiveFiniteNumber(row?.readiness_score, row?.recovery_score) ??
            state?.readiness_score ??
            0;
          this.hrv = Math.round(Number(row?.hrv_rmssd ?? state?.hrv_rmssd ?? 0));
          const sleepMin =
            Number(row?.sleep_duration_min) ||
            (state?.sleep_hours != null ? Number(state.sleep_hours) * 60 : 0);
          this.sleep = Number((sleepMin / 60).toFixed(1));
        }
      }
      if (planData) this.plan = planData;
      if (workoutsData) {
        this.workouts = workoutsData;
        this.workoutsComplete = workoutsData.length < 200;
      }

      console.log('[AthleteStore] Tier 2 complete — charts and history ready');

      // Persist to cache after both tiers are loaded so subsequent visits hydrate instantly.
      if (athleteId) this.persistCurrent(athleteId);
    });
  }

  async loadMoreBiometrics() {
    if (this.biometricsLoadingMore) return false;
    const page = this.biometrics?.page;
    const nextBefore = page?.next_before;
    const hasMore = !!page?.has_more;
    if (!hasMore || !nextBefore) return false;

    this.biometricsLoadingMore = true;
    const gen = this._gen;
    try {
      const more = await api.getBiometricsPage({ limit: 60, before: nextBefore });
      if (!this.current(gen) || !more?.series?.length) return false;

      const existing = Array.isArray(this.biometrics?.series) ? this.biometrics.series : [];
      const mergedSeries = [...more.series, ...existing];

      const merged = {
        ...this.biometrics,
        ...more,
        series: mergedSeries,
        hrvData: [...(more.hrvData || []), ...(this.biometrics?.hrvData || [])],
        sleepData: [...(more.sleepData || []), ...(this.biometrics?.sleepData || [])],
        sleepScores: [...(more.sleepScores || []), ...(this.biometrics?.sleepScores || [])],
        page: more.page,
      };

      this.biometrics = merged;
      return true;
    } catch (e) {
      console.error('[AthleteStore] loadMoreBiometrics error:', e);
      return false;
    } finally {
      if (this.current(gen)) this.biometricsLoadingMore = false;
    }
  }

  /**
   * Load older workouts until the store reaches back to `day` (YYYY-MM-DD) or there are no more.
   * The first load is the newest 200, so views showing an older week or month used to come up
   * empty (e.g. nothing before mid-June for an athlete with 684 workouts).
   */
  async ensureWorkoutsFrom(day: string): Promise<void> {
    if (this._workoutsLoadingMore) return this._workoutsLoadingMore;
    const gen = this._gen;
    const run = async () => {
      for (let i = 0; i < 20 && !this.workoutsComplete && this.current(gen); i++) {
        const oldest = this.workouts.reduce<string | null>(
          (m, w) => (w?.started_at && (!m || w.started_at < m) ? w.started_at : m),
          null
        );
        if (!oldest || oldest.slice(0, 10) < day) return;
        const more = await api.getCompletedWorkouts(200, oldest);
        if (!this.current(gen)) return;
        if (!Array.isArray(more)) return; // network error: try again next time
        const seen = new Set(this.workouts.map((w) => w?.id));
        this.workouts = [...this.workouts, ...more.filter((w: any) => !seen.has(w?.id))];
        if (more.length < 200) this.workoutsComplete = true;
      }
    };
    this._workoutsLoadingMore = run().finally(() => {
      this._workoutsLoadingMore = null;
    });
    return this._workoutsLoadingMore;
  }

  /** Load older biometrics pages until the series reaches back to `day` (YYYY-MM-DD). */
  async ensureBiometricsFrom(day: string): Promise<void> {
    for (let i = 0; i < 20; i++) {
      const series = this.biometrics?.series;
      const oldest = Array.isArray(series) && series.length ? String(series[0]?.date ?? '') : '';
      if (!oldest || oldest <= day || !this.biometrics?.page?.has_more) return;
      if (!(await this.loadMoreBiometrics())) return;
    }
  }

  /**
   * Re-reads the athlete profile from the API (bypassing the cached copy), so screens
   * that show or edit profile values always start from what's in the database.
   */
  async refreshProfile(): Promise<boolean> {
    const gen = this._gen;
    try {
      const fresh = await api.getAthleteProfile();
      if (!fresh || !this.current(gen)) return false;
      this.profile = fresh;
      const athleteId = authStore.user?.id ?? null;
      if (athleteId) this.persistCurrent(athleteId);
      return true;
    } catch {
      return false;
    }
  }

  async updateProfile(payload: any): Promise<boolean> {
    this.lastProfileSaveError = null;
    const gen = this._gen;
    this._profileWrites++;
    const res = await api.patchAthleteProfile(payload);
    if (!this.current(gen)) return false;
    if (!res.ok) {
      this.lastProfileSaveError = res.error;
      return false;
    }
    const data = res.data as { status?: string };
    if (data?.status === 'success') {
      const fresh = await api.getAthleteProfile();
      if (!this.current(gen)) return false;
      if (fresh) this.profile = fresh;
      if (payload && payload.weight_kg != null) {
        // The backend records a typed-in weight as today's reading; reload the series so
        // every screen that shows "latest weight" picks it up.
        try {
          const bio = await api.getBiometricsPage({ limit: 60 });
          if (bio && this.current(gen)) this.biometrics = bio;
        } catch {
          // keep the old series; the profile copy is still current
        }
      }
      const athleteId = authStore.user?.id ?? null;
      if (athleteId) this.persistCurrent(athleteId);
      return true;
    }
    this.lastProfileSaveError = 'Failed to save changes. Please try again.';
    return false;
  }

  async deleteAccount() {
    const res = await api.deleteAthleteAccount();
    return res && res.status === 'success';
  }

  async deleteWorkout(workoutId: string) {
    const res = await api.deleteWorkout(workoutId);
    if (res && res.status === 'success') {
      this.workouts = this.workouts.filter(w => w.id !== workoutId);
      const athleteId = authStore.user?.id ?? null;
      if (athleteId) this.persistCurrent(athleteId);
      return true;
    }
    return false;
  }

  async addWorkout(payload: object): Promise<boolean> {
    const result = await api.post('/v1/workouts', payload);
    if (!result) return false;
    await this.fetchAll(true);
    return true;
  }

  async updateWorkout(workoutId: string, payload: object): Promise<any | boolean> {
    const result = await api.updateWorkout(workoutId, payload);
    if (!result || result.status !== 'success') return false;
    await this.fetchAll(true);
    return result.workout ?? true;
  }

  async addSleep(payload: object): Promise<boolean> {
    const result = await api.post('/v1/biometrics/daily', payload);
    if (!result) return false;
    await this.fetchAll(true);
    return true;
  }

  async unlinkIntegration(provider: string) {
    console.log(`[AthleteStore] unlinkIntegration(${provider})`);
    const res = await api.unlinkIntegration(provider);
    if (res && res.status === 'success') {
      const syncData = await api.getSyncStatus();
      if (syncData) this.syncStatus = syncData;
      return true;
    }
    console.warn(`[AthleteStore] unlinkIntegration(${provider}) failed`, res);
    return false;
  }
}

export const athleteStore = new AthleteState();

// Initialization moved to root layout to handle auth state correctly
