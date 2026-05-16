import { api } from '../api';
import { calculateSleepScore, calculateRecoveryScore } from '../utils/biometrics';

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
    this.initialLoadDone = false; // $state — assignment triggers reactivity
  }

  async fetchAll(force = false) {
    if (this.loading || (this.initialLoadDone && !force)) return;
    
    console.log("[AthleteStore] Starting fetchAll");
    this.loading = true;

    try {
      // Parallel fetch all data
      const results = await Promise.allSettled([
        api.getAthleteState(),
        api.getAthleteMetrics(),
        api.getBiometricsPage({ limit: 60 }),
        api.getPlan(),
        api.getAthleteProfile(),
        api.getCompletedWorkouts(200),
        api.getSyncStatus()
      ]);

      const [state, metricsData, biometricsData, planData, profileData, workoutsData, syncData] = results.map(r => r.status === 'fulfilled' ? r.value : null);

      console.log("[AthleteStore] Data fetched:", { 
        hasProfile: !!profileData, 
        workoutsCount: workoutsData?.length, 
        biometricsSeriesCount: biometricsData?.series?.length,
        syncStatus: syncData
      });

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

      if (metricsData) this.metrics = metricsData;
      if (biometricsData) this.biometrics = biometricsData;
      if (planData) this.plan = planData;
      if (profileData) this.profile = profileData;
      if (workoutsData) this.workouts = workoutsData;
      if (syncData) this.syncStatus = syncData;
      
      // Use pre-calculated Astrape scores from the database
      if (this.biometrics?.series?.length > 0) {
        const latest = this.biometrics.series[this.biometrics.series.length - 1];
        // Priority: Astrape Readiness > Astrape Recovery > legacy readiness/recovery
        this.readiness = latest.readiness_score || latest.recovery_score || state?.readiness_score || 0;
        this.hrv = Math.round(latest.hrv_rmssd || 0);
        this.sleep = Number(((latest.sleep_duration_min || 0) / 60).toFixed(1));
      }

      this.initialLoadDone = true;
      console.log('[AthleteStore] fetchAll completed successfully');

      // Sync timezone offset to ensure biological day alignment
      const currentOffset = -new Date().getTimezoneOffset(); // e.g., -300 for EST
      if (this.profile && this.profile.timezone_offset_min !== currentOffset) {
        console.log(`[AthleteStore] Updating timezone offset: ${this.profile.timezone_offset_min} -> ${currentOffset}`);
        this.updateProfile({ timezone_offset_min: currentOffset });
      }
    } catch (e) {
      console.error('[AthleteStore] Error in fetchAll:', e);
    } finally {
      this.loading = false;
    }
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

      // Merge chart arrays as well (they are ordered oldest->newest)
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

  async updateProfile(payload: any) {
    const res = await api.patchAthleteProfile(payload);
    if (res && res.status === 'success') {
      // Merge the updated fields directly into the reactive profile state
      // instead of re-fetching all 7 endpoints — avoids unnecessary lag.
      const fresh = await api.getAthleteProfile();
      if (fresh) this.profile = fresh;
      return true;
    }
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
      return true;
    }
    return false;
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
