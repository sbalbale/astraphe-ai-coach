import { api } from '../api';
import { authStore } from './authStore.svelte';
import { calculateSleepScore, calculateRecoveryScore } from '../utils/biometrics';

const CACHE_KEY = 'astrape:athlete-cache:v1';
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
  lastProfileSaveError = $state<string | null>(null);

  // Non-reactive dedup flag so two simultaneous fetchAll() calls don't trigger
  // duplicate background refreshes (layout effect + dashboard onMount fire in quick succession).
  private _refreshing = false;
  private _lastRefreshAt = 0; // timestamp of last completed background refresh

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

  async fetchAll(force = false) {
    if (this.loading) return;

    const athleteId = authStore.user?.id ?? null;

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
      const [stateResult, profileResult, syncResult] = await Promise.allSettled([
        api.getAthleteState(),
        api.getAthleteProfile(),
        api.getSyncStatus()
      ]);

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
      if (profileData) this.profile = profileData;
      if (syncData) this.syncStatus = syncData;

      this.initialLoadDone = true;
      this.loading = false;

      console.log('[AthleteStore] Tier 1 complete — dashboard ready');

      const currentOffset = -new Date().getTimezoneOffset();
      if (this.profile && this.profile.timezone_offset_min !== currentOffset) {
        console.log(`[AthleteStore] Updating timezone offset: ${this.profile.timezone_offset_min} -> ${currentOffset}`);
        this.updateProfile({ timezone_offset_min: currentOffset });
      }

      // Tier 2 background enrichment + persist cache on completion.
      this.loadTier2(athleteId, state);

    } catch (e) {
      console.error('[AthleteStore] Error in fetchAll:', e);
      this.loading = false;
      this.initialLoadDone = true;
    }
  }

  private async refreshInBackground(athleteId: string | null) {
    // Refresh both tiers silently. Does NOT touch `loading` so the UI keeps showing cached data.
    if (this._refreshing) return;
    this._refreshing = true;
    try {
      const [stateResult, profileResult, syncResult] = await Promise.allSettled([
        api.getAthleteState(),
        api.getAthleteProfile(),
        api.getSyncStatus()
      ]);

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
      if (profileData) this.profile = profileData;
      if (syncData) this.syncStatus = syncData;

      this.loadTier2(athleteId, state);
    } catch (e) {
      console.error('[AthleteStore] Background refresh error:', e);
    } finally {
      this._refreshing = false;
      this._lastRefreshAt = Date.now();
    }
  }

  private loadTier2(athleteId: string | null, state: any) {
    Promise.allSettled([
      api.getAthleteMetrics(),
      api.getBiometricsPage({ limit: 60 }),
      api.getPlan(),
      api.getCompletedWorkouts(200)
    ]).then(([metricsResult, bioResult, planResult, workoutsResult]) => {
      const metricsData = metricsResult.status === 'fulfilled' ? metricsResult.value : null;
      const biometricsData = bioResult.status === 'fulfilled' ? bioResult.value : null;
      const planData = planResult.status === 'fulfilled' ? planResult.value : null;
      const workoutsData = workoutsResult.status === 'fulfilled' ? workoutsResult.value : null;

      if (metricsData) this.metrics = metricsData;
      if (biometricsData) {
        this.biometrics = biometricsData;
        if (this.biometrics?.series?.length > 0) {
          const latest = this.biometrics.series[this.biometrics.series.length - 1];
          this.readiness = latest.readiness_score || latest.recovery_score || state?.readiness_score || 0;
          this.hrv = Math.round(latest.hrv_rmssd || 0);
          this.sleep = Number(((latest.sleep_duration_min || 0) / 60).toFixed(1));
        }
      }
      if (planData) this.plan = planData;
      if (workoutsData) this.workouts = workoutsData;

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
    try {
      const more = await api.getBiometricsPage({ limit: 60, before: nextBefore });
      if (!more?.series?.length) return false;

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
      this.biometricsLoadingMore = false;
    }
  }

  async updateProfile(payload: any): Promise<boolean> {
    this.lastProfileSaveError = null;
    const res = await api.patchAthleteProfile(payload);
    if (!res.ok) {
      this.lastProfileSaveError = res.error;
      return false;
    }
    const data = res.data as { status?: string };
    if (data?.status === 'success') {
      const fresh = await api.getAthleteProfile();
      if (fresh) this.profile = fresh;
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
