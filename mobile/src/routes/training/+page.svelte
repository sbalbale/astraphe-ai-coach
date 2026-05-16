<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const trainingLoadAnalysisMemo = new SvelteMap<string, string | null>();
  const workoutAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import DonutChart from '$lib/components/charts/DonutChart.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { confirm } from '$lib/confirm';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { page } from '$app/stores';
  import { addDays, endOfWeek, format, startOfWeek } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import { formCssColor, getWeeklyLoadDeltaColor } from '$lib/scoreColors';
  import { Lightbulb } from 'lucide-svelte';
  import {
    getActivityStreams,
    getActivityLaps,
    getActivityIntervals,
    getActivityZones,
    hydrateActivityStreams,
    type ActivityStreams,
    type ActivityLap,
    type ActivityIntervals,
    type ActivityZones,
  } from '$lib/services/activityService';
  import { stravaPolylineFromPayload } from '$lib/utils/polyline';
  import StreamCharts from '$lib/components/workout/StreamCharts.svelte';
  import IntervalsTable from '$lib/components/workout/IntervalsTable.svelte';
  import GpsTrace from '$lib/components/workout/GpsTrace.svelte';
  import LapStrip from '$lib/components/workout/LapStrip.svelte';
  import DataSources from '$lib/components/workout/DataSources.svelte';

  const CTL_IDENTITY_HEX = '#3b82f6';
  const ATL_IDENTITY_HEX = '#64748b';

  let metric = $state('load');
  const tabs = ['load', 'history']; // Simplified tabs for now as pace/zones need complex processing
  // Avoid UI flicker: `syncStatus` can be briefly null/undefined even when workouts are loaded.
  // Only show "No Training Data" once we know initial load is done and we truly have no workouts.
  const hasWorkouts = $derived(athleteStore.workouts?.length > 0);
  const isConnected = $derived(
    athleteStore.syncStatus
      ? Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected)
      : true
  );
  const showNoTrainingData = $derived(athleteStore.initialLoadDone && !athleteStore.loading && !isConnected && !hasWorkouts);

  let selectedWorkout = $state<any>(null);
  let workoutAnalysisText = $state<string | null>(null);
  let workoutAnalysisLoading = $state(false);

  let detailStreams = $state<ActivityStreams | null>(null);
  let detailLaps = $state<ActivityLap[]>([]);
  let detailIntervals = $state<ActivityIntervals | null>(null);
  let detailZones = $state<ActivityZones | null>(null);
  let detailLoading = $state(false);
  let detailHydrating = $state(false);
  let detailError = $state<string | null>(null);

  const detailStravaPolyline = $derived(
    selectedWorkout ? stravaPolylineFromPayload(selectedWorkout.raw_strava_payload) : null
  );

  const zoneColors = ['#AAB3BF', '#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791'];

  // Week selector (History tab)
  // Source of truth is the picked day (YYYY-MM-DD). We derive the Monday week start from it.
  let weekPickerValue = $state('');
  let appliedWorkoutIdFromUrl = $state(false);

  function parseDateInputLocal(value: string): Date {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!m) return new Date(value);
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    // Use local time to avoid timezone shifting when parsing YYYY-MM-DD
    return new Date(y, mo - 1, d, 12, 0, 0, 0);
  }

  $effect(() => {
    if (!weekPickerValue) weekPickerValue = format(new Date(), 'yyyy-MM-dd');
  });

  const selectedWeekStart = $derived.by(() => startOfWeek(parseDateInputLocal(weekPickerValue), { weekStartsOn: 1 }));
  const selectedWeekEnd = $derived(endOfWeek(selectedWeekStart, { weekStartsOn: 1 }));
  const selectedWeekEndStr = $derived(format(selectedWeekEnd, 'yyyy-MM-dd'));
  function jumpToCurrentWeek() {
    weekPickerValue = format(new Date(), 'yyyy-MM-dd');
  }

  const workoutIdFromUrl = $derived($page.url.searchParams.get('workout_id'));
  $effect(() => {
    if (appliedWorkoutIdFromUrl) return;
    if (!workoutIdFromUrl) return;
    if (!hasWorkouts) return;

    const match = (athleteStore.workouts || []).find((w) => String(w?.id) === String(workoutIdFromUrl));
    if (!match) return;

    metric = 'history';
    weekPickerValue = format(new Date(match.started_at), 'yyyy-MM-dd');
    selectedWorkout = match;
    appliedWorkoutIdFromUrl = true;
  });

  const weekWorkouts = $derived.by(() => {
    const start = selectedWeekStart.getTime();
    const end = selectedWeekEnd.getTime();
    return (athleteStore.workouts || []).filter((w) => {
      const t = w?.started_at ? new Date(w.started_at).getTime() : NaN;
      return Number.isFinite(t) && t >= start && t <= end;
    });
  });

  function getWorkoutIcon(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run' || t === 'running') return '🏃';
    if (t === 'bike' || t === 'cycling') return '🚴';
    if (t === 'row' || t === 'rowing') return '🚣';
    if (t === 'swim' || t === 'swimming') return '🏊';
    if (t === 'strength' || t === 'strength_training' || t === 'gym') return '💪';
    if (t === 'mobility') return '🧘';
    return '⭐';
  }

  function getWorkoutLabel(type: string) {
    const t = type?.toLowerCase();
    if (t === 'strength_training' || t === 'strength' || t === 'gym') return 'Strength';
    if (t === 'mobility') return 'Mobility';
    if (t === 'other') return 'Other';
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Workout';
  }

  function getWorkoutColor(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run' || t === 'running') return 'var(--blue)';
    if (t === 'bike' || t === 'cycling') return 'var(--teal)';
    if (t === 'row' || t === 'rowing') return 'var(--amber)';
    if (t === 'mobility') return '#a855f7';
    if (t === 'other') return 'var(--amber)';
    return 'var(--text2)';
  }

  function getWorkoutBg(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run' || t === 'running') return 'bg-blue-dim border-blue-glow';
    if (t === 'bike' || t === 'cycling') return 'bg-teal-dim border-[rgba(0,200,168,0.3)]';
    if (t === 'row' || t === 'rowing') return 'bg-amber-dim border-[rgba(255,203,136,0.3)]';
    if (t === 'mobility') return 'bg-glass border-[rgba(168,85,247,0.35)]';
    if (t === 'other') return 'bg-glass border-[rgba(234,179,8,0.35)]';
    return 'bg-glass border-border';
  }

  const weeklyTss = $derived(athleteStore.workouts?.slice(0, 7).reduce((acc, w) => acc + (w.tss || 0), 0) || 0);

  /** Oldest→newest daily rows for baseline math */
  const trainingLoadSorted = $derived.by(() =>
    [...(athleteStore.metrics?.trainingLoadData ?? [])]
      .filter((r: any) => r?.date)
      .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
  );

  /** Rolling 7-day TSS vs mean of prior (up to six) trailing 7-day windows */
  const weeklyRollingContext = $derived.by(() => {
    const rows = trainingLoadSorted;
    const n = rows.length;
    const sumWindowEnding = (endEx: number) => {
      if (endEx < 7) return null as number | null;
      let s = 0;
      for (let i = endEx - 7; i < endEx; i++) s += Number((rows[i] as any)?.daily_tss ?? 0);
      return s;
    };

    if (n >= 7) {
      const current = sumWindowEnding(n)!;
      const historics: number[] = [];
      for (let end = n - 7; end >= 14 && historics.length < 8; end -= 7) {
        const v = sumWindowEnding(end);
        if (v != null) historics.push(v);
      }
      if (historics.length > 0) {
        const baseline = historics.reduce((a, b) => a + b, 0) / historics.length;
        const delta = current - baseline;
        const pct = delta / Math.max(baseline, 1e-6);
        return {
          weekSum: Math.round(current),
          baseline: Math.round(baseline),
          delta: Math.round(delta),
          pct
        };
      }
      return { weekSum: Math.round(current), baseline: null, delta: null, pct: null as number | null };
    }

    return {
      weekSum: Math.round(weeklyTss),
      baseline: null,
      delta: null,
      pct: null as number | null
    };
  });

  function getDurationSecs(w: any): number {
    const direct = w?.duration_secs ?? w?.duration_seconds;
    if (Number.isFinite(direct)) return Math.max(0, Math.floor(Number(direct)));

    const start = w?.started_at ? new Date(w.started_at) : null;
    const end = w?.ended_at ? new Date(w.ended_at) : null;
    if (!start || !end) return 0;
    const ms = end.getTime() - start.getTime();
    if (!Number.isFinite(ms)) return 0;
    return Math.max(0, Math.floor(ms / 1000));
  }

  function formatMMSS(totalSeconds: number): string {
    const s = Math.max(0, Math.floor(totalSeconds || 0));
    const m = Math.floor(s / 60);
    const ss = String(s % 60).padStart(2, '0');
    return `${m}:${ss}`;
  }

  function getHrZonePcts(w: any): Array<number | null> {
    const z1 = w?.hr_zone_1_pct ?? null;
    const z2 = w?.hr_zone_2_pct ?? null;
    const z3 = w?.hr_zone_3_pct ?? null;
    const z4 = w?.hr_zone_4_pct ?? null;
    const z5 = w?.hr_zone_5_pct ?? null;
    const z0 =
      w?.hr_zone_0_pct ?? (z1 == null ? null : Math.max(0, 100 - Number(z1 || 0) - Number(z2 || 0) - Number(z3 || 0) - Number(z4 || 0) - Number(z5 || 0)));

    return [
      z0,
      w?.hr_zone_1_pct ?? null,
      w?.hr_zone_2_pct ?? null,
      w?.hr_zone_3_pct ?? null,
      w?.hr_zone_4_pct ?? null,
      w?.hr_zone_5_pct ?? null
    ].map((v) => (v == null ? null : Number(v)));
  }

  function getHrZonePctsTopDown(w: any): Array<number | null> {
    // Display order: Z5 (top) -> Z0 (bottom)
    return getHrZonePcts(w).slice().reverse();
  }

  function hasAnyHrZone(w: any): boolean {
    return getHrZonePcts(w).some((v) => v != null);
  }

  async function deleteSelectedWorkout() {
    if (!selectedWorkout?.id) return;
    const ok = await confirm({
      title: 'Delete workout?',
      message: 'Delete this workout? This cannot be undone.',
      confirmText: 'Delete',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (!ok) return;
    try {
      await athleteStore.deleteWorkout(selectedWorkout.id);
      selectedWorkout = null;
    } catch (e) {
      console.error(e);
      alert('Failed to delete workout');
    }
  }

  async function loadWorkoutAnalysis(workoutId: string) {
    if (authStore.tier !== 'premium') return;

    if (workoutAnalysisMemo.has(workoutId)) {
      workoutAnalysisText = workoutAnalysisMemo.get(workoutId) ?? null;
      return;
    }

    workoutAnalysisLoading = true;
    try {
      const res = await api.get(`/v1/analysis/workout/${workoutId}`);
      const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : null;
      workoutAnalysisMemo.set(workoutId, content);
      if (selectedWorkout?.id === workoutId) workoutAnalysisText = workoutAnalysisMemo.get(workoutId) ?? null;
    } finally {
      workoutAnalysisLoading = false;
    }
  }

  $effect(() => {
    const workoutId = selectedWorkout?.id;
    if (!workoutId) {
      workoutAnalysisText = null;
      return;
    }
    void loadWorkoutAnalysis(workoutId);
  });

  $effect(() => {
    const w = selectedWorkout;

    detailStreams = null;
    detailLaps = [];
    detailIntervals = null;
    detailZones = null;
    detailError = null;
    detailLoading = false;
    detailHydrating = false;

    if (!w?.id || !w.strava_activity_id) return;

    let cancelled = false;
    detailLoading = true;

    (async () => {
      try {
        let [streams, laps, intervals, zones] = await Promise.all([
          getActivityStreams(w.id),
          getActivityLaps(w.id),
          getActivityIntervals(w.id),
          getActivityZones(w.id),
        ]);

        if (cancelled) return;

        if (!streams && w.strava_activity_id) {
          detailHydrating = true;
          const hydrated = await hydrateActivityStreams(w.id);
          if (cancelled) return;
          if (hydrated && (hydrated.status === 'hydrated' || hydrated.status === 'already_stored')) {
            streams = await getActivityStreams(w.id);
            if (!zones || (zones.data_points === 0 && zones.source !== 'summary')) {
              zones = await getActivityZones(w.id);
            }
          }
        }

        if (cancelled) return;
        detailStreams = streams;
        detailLaps = laps ?? [];
        detailIntervals = intervals;
        detailZones = zones;
      } catch (e: unknown) {
        if (!cancelled) detailError = e instanceof Error ? e.message : 'Failed to load workout details';
      } finally {
        if (!cancelled) {
          detailLoading = false;
          detailHydrating = false;
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  });

  let analysisText = $state<string | null>(null);
  let analysisLoading = $state(false);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    const scopeKey = selectedWeekEndStr;
    if (!scopeKey) {
      analysisText = null;
      return;
    }

    const cached = trainingLoadAnalysisMemo.get(scopeKey);
    if (cached !== undefined) {
      analysisText = cached;
      return;
    }

    analysisText = null;

    const requestKey = `training-analysis:${scopeKey}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        analysisLoading = true;
        const res = await api.get<{ analysis: { content: string } }>(`/v1/analysis/training-load?end_day=${scopeKey}`);
        const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
        if (activeAnalysisKey !== requestKey) return;
        const next = content || null;
        trainingLoadAnalysisMemo.set(scopeKey, next);
        analysisText = next;
      } catch {
        if (activeAnalysisKey !== requestKey) return;
        trainingLoadAnalysisMemo.set(scopeKey, null);
      } finally {
        if (activeAnalysisKey === requestKey) analysisLoading = false;
      }
    })();
  });
</script>

<div class="flex flex-col gap-3">
  <h1 class="text-[20px] font-bold tracking-[-0.02em] text-slate-200 pt-1">Training Analysis</h1>

  {#if showNoTrainingData}
    <EmptyState 
      title="No Training Data" 
      message="Connect your training apps to analyze your performance trends and history."
    />
  {:else if !hasWorkouts}
    <EmptyState 
      title="Waiting for Workouts" 
      message="We're waiting for your training history to sync from your connected services."
      icon="⏳"
    />
  {:else}
    <!-- Metric Tabs -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each tabs as tab (tab)}
        <Pill active={metric === tab} onclick={() => { metric = tab; selectedWorkout = null; }}>
          {tab.charAt(0).toUpperCase() + tab.slice(1)}
        </Pill>
      {/each}
    </div>

    {#if metric === 'load'}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
        <Card paddingClass="px-6 py-5">
          <div class="flex flex-col justify-start items-start w-full">
            <MetricBadge
              label="Fitness (CTL)"
              value={Math.round(athleteStore.ctl)}
              color={CTL_IDENTITY_HEX}
              sub="Long-term load"
              labelClass="text-[10px] text-slate-400 uppercase tracking-[0.08em] font-mono"
              subClass="text-[10px] text-slate-400"
            />
          </div>
        </Card>
        <Card paddingClass="px-6 py-5">
          <div class="flex flex-col justify-start items-start w-full">
            <MetricBadge
              label="Fatigue (ATL)"
              value={Math.round(athleteStore.atl)}
              color={ATL_IDENTITY_HEX}
              sub="Short-term load"
              labelClass="text-[10px] text-slate-400 uppercase tracking-[0.08em] font-mono"
              subClass="text-[10px] text-slate-400"
              valueClassName="text-slate-200"
            />
          </div>
        </Card>
        <Card paddingClass="px-6 py-5">
          <div class="flex flex-col justify-start items-start w-full">
            <MetricBadge
              label="Form (TSB)"
              value={athleteStore.tsb > 0 ? `+${Math.round(athleteStore.tsb)}` : Math.round(athleteStore.tsb)}
              color={formCssColor(athleteStore.tsb)}
              sub="Training balance"
              labelClass="text-[10px] text-slate-400 uppercase tracking-[0.08em] font-mono"
              subClass="text-[10px] text-slate-400"
            />
          </div>
        </Card>
        <Card paddingClass="px-6 py-5">
          <div class="flex flex-col justify-start items-start w-full leading-tight">
            <div class="flex flex-col gap-0.5 w-full">
              <span class="text-[10px] font-mono uppercase tracking-wide text-slate-400">Weekly TSS</span>
              <div class="flex flex-col gap-1">
                <p class="text-[22px] font-semibold tabular-nums leading-none text-slate-200 tracking-[-0.02em]">
                  {weeklyRollingContext.weekSum}
                </p>
                {#if weeklyRollingContext.baseline !== null && weeklyRollingContext.delta !== null && weeklyRollingContext.pct !== null}
                  {@const delta = weeklyRollingContext.delta}
                  <div class="flex flex-row flex-wrap items-baseline gap-x-2 gap-y-0">
                    <span class="text-[10px] font-mono tabular-nums text-slate-400">
                      Baseline: {weeklyRollingContext.baseline}
                    </span>
                    <span class="text-[10px] font-mono tabular-nums {getWeeklyLoadDeltaColor(weeklyRollingContext.pct)}">
                      {#if delta > 0}
                        ↑ {delta}
                      {:else if delta < 0}
                        ↓ {Math.abs(delta)}
                      {:else}
                        0
                      {/if}
                    </span>
                  </div>
                {/if}
              </div>
            </div>
          </div>
        </Card>
      </div>
      
      {#if athleteStore.metrics?.trainingLoadData?.length > 0}
        <Card>
          <p class="text-[13px] font-semibold mb-3 text-slate-200">Training Load Trend</p>
          <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
        </Card>
      {/if}
      
      <Card
        paddingClass="px-6 py-4"
        style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);"
      >
        <div class="flex gap-3 items-start">
          <Lightbulb class="w-4 h-4 shrink-0 text-slate-500 mt-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div class="flex-1 min-w-0">
            <p class="text-[13px] font-semibold mb-1.5 text-slate-400">Load Insight</p>
            {#if analysisLoading && analysisText === null}
              <p class="text-xs text-text2 animate-pulse">Analyzing...</p>
            {:else}
              <p class="text-xs text-slate-300 leading-relaxed">
                {analysisText ??
                  (athleteStore.tsb > 10
                    ? `You have significant freshness (TSB +${Math.round(athleteStore.tsb)}). Excellent time for a peak performance or hard test.`
                    : athleteStore.tsb < -20
                      ? 'High fatigue detected. Consider a deload week to allow CTL to catch up to ATL safely.'
                      : 'Your training load is stable. Continue with your planned progression.')}
              </p>
            {/if}
          </div>
        </div>
      </Card>
    {/if}

    {#if metric === 'history'}
      {#if selectedWorkout}
        <!-- Detailed Workout View -->
        <div class="mb-2 flex items-center justify-between gap-2">
          <button
            class="text-xs text-blue flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer"
            onclick={() => (selectedWorkout = null)}
          >
            ← Back to list
          </button>

          <button
            class="text-xs text-red bg-transparent border-none p-0 cursor-pointer"
            onclick={deleteSelectedWorkout}
          >
            Delete
          </button>
        </div>
        
        <Card>
          {@const selectedStrainVal = Number.isFinite(Number(selectedWorkout?.strain_score)) ? Math.round(Number(selectedWorkout.strain_score)) : null}
          {@const selectedTssVal = Number.isFinite(Number(selectedWorkout?.tss)) ? Math.round(Number(selectedWorkout.tss)) : null}
          <div class="flex items-center gap-4 mb-4">
            <div class="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl {getWorkoutBg(selectedWorkout.sport)}">
              {getWorkoutIcon(selectedWorkout.sport)}
            </div>
            <div class="flex-1">
              <h2 class="text-lg font-bold leading-tight text-text0">{selectedWorkout.title || (getWorkoutLabel(selectedWorkout.sport) + ' Session')}</h2>
              <p class="text-xs text-text2">{format(new Date(selectedWorkout.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'EEEE, MMM d · HH:mm' : 'EEEE, MMM d · h:mm a')}</p>
            </div>
            <div class="text-right flex flex-col gap-1">
              <div>
                <p class="text-[18px] font-bold tabular-nums" style:color={boundedScoreCssColor(selectedStrainVal, true)}>
                  {selectedStrainVal === null ? '--' : selectedStrainVal}
                </p>
                <p class="text-[9px] text-text2 font-mono">STRAIN</p>
              </div>
              <div>
                <p
                  class="text-[18px] font-bold tabular-nums"
                  style:color={boundedScoreCssColor(selectedTssVal === null ? null : selectedStrainVal, true)}
                >
                  {selectedTssVal === null ? '--' : selectedTssVal}
                </p>
                <p class="text-[9px] text-text2 font-mono">TSS</p>
              </div>
            </div>
          </div>

          <div class="grid grid-cols-3 gap-2 mb-5">
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Duration</p>
              <p class="text-sm font-bold">{Math.floor(getDurationSecs(selectedWorkout) / 60)}m</p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Distance</p>
              <p class="text-sm font-bold">{selectedWorkout.distance_m ? (selectedWorkout.distance_m / 1000).toFixed(2) + 'km' : '--'}</p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Avg HR</p>
              <p class="text-sm font-bold">{selectedWorkout.avg_hr || '--'} <span class="text-[10px] font-normal opacity-60">bpm</span></p>
            </div>
          </div>

          <div class="mb-5 bg-glass2 p-3 rounded-xl border border-border">
            <p class="text-[11px] font-semibold mb-2">Heart-rate zones</p>

            {#if hasAnyHrZone(selectedWorkout)}
              <div class="flex flex-col gap-2">
                {#each getHrZonePctsTopDown(selectedWorkout) as pct, topIdx (topIdx)}
                  {@const zone = 5 - topIdx}
                  {@const color = zoneColors[zone]}
                  <div class="flex items-center gap-3">
                    <div class="w-9 shrink-0 flex items-center gap-2">
                      <span class="w-2 h-2 rounded-full shrink-0" style="background: {color};"></span>
                      <p class="text-[11px] text-text1 font-mono uppercase">Z{zone}</p>
                    </div>

                    <div class="flex-1">
                      <div class="h-2.5 rounded-full bg-glass border border-border overflow-hidden">
                        <div
                          class="h-full rounded-full"
                          style="width: {pct == null ? 0 : Math.max(0, Math.min(100, pct))}%; background: {color};"
                        ></div>
                      </div>
                    </div>

                    <div class="w-[92px] shrink-0 text-right">
                      <p class="text-[11px] text-text2 font-mono">{pct == null ? '--' : `${Math.round(pct)}%`}</p>
                      <p class="text-[11px] text-text1 font-semibold tabular-nums">
                        {pct == null ? '--' : formatMMSS((getDurationSecs(selectedWorkout) * pct) / 100)}
                      </p>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-[11px] text-text2">No zone data for this workout</p>
            {/if}
          </div>

          {#if authStore.tier === 'premium'}
            <div class="mt-4 pt-4 border-t border-border/40"
                 style="background: linear-gradient(135deg, rgba(70,33,255,0.08), transparent); border-radius: 12px; padding: 12px;">
              <div class="flex items-center gap-1.5 mb-2">
                <span class="text-[11px] font-mono uppercase tracking-[0.08em] text-blue">AI Insight</span>
                <Tag color="var(--blue)">ASTRAPE</Tag>
              </div>
              {#if workoutAnalysisLoading && !workoutAnalysisMemo.has(selectedWorkout.id)}
                <p class="text-xs text-text2 animate-pulse">Analyzing workout...</p>
              {:else}
                <p class="text-xs text-text1 leading-relaxed">
                  {workoutAnalysisMemo.get(selectedWorkout.id) ?? 'Insight unavailable.'}
                </p>
              {/if}
            </div>
          {:else}
            <div class="p-3 bg-blue-dim rounded-xl border-l-2 border-blue">
              <p class="text-[11px] font-semibold text-blue mb-1">Analysis</p>
              <p class="text-[11px] text-text1 leading-relaxed">
                This session contributed {Math.round(selectedWorkout.tss || 0)} points to your acute load. {selectedWorkout.tss > 80 ? 'Ensure proper recovery tonight.' : 'Good aerobic contribution.'}
              </p>
            </div>
          {/if}

          <div class="mt-5 pt-4 border-t border-border">
            <DataSources workout={selectedWorkout} />
          </div>

          {#if selectedWorkout.strava_activity_id}
            {#if detailLoading}
              <div class="mt-4 space-y-3">
                {#each [150, 150, 120] as h}
                  <div class="rounded-2xl bg-glass animate-pulse" style="height: {h}px;"></div>
                {/each}
              </div>

            {:else if detailError}
              <p class="text-[11px] text-red mt-3 font-mono">{detailError}</p>

            {:else}
              {#if selectedWorkout.strava_streams_fetched === false}
                <p class="text-[11px] text-text2 font-mono mt-3 leading-relaxed">
                  Strava is linked, but stream data has not been imported for this workout yet. Reconnect
                  Strava or run the Strava backfill script to load charts and GPS.
                </p>
              {:else if detailHydrating}
                <p class="text-[11px] text-text2 font-mono mt-3 animate-pulse">
                  Loading stream data from Strava…
                </p>
              {:else if !detailStreams && selectedWorkout.strava_streams_fetched}
                <p class="text-[11px] text-text2 font-mono mt-3">
                  No stream data stored for this workout (Strava may have returned no streams for this activity).
                </p>
              {/if}

              {#if detailLaps.length >= 2}
                <div class="mt-4">
                  <LapStrip laps={detailLaps} sport={selectedWorkout.sport} />
                </div>
              {/if}

              {#if detailStreams}
                <div class="mt-4">
                  <StreamCharts
                    streams={detailStreams}
                    laps={detailLaps}
                    sport={selectedWorkout.sport}
                  />
                </div>
              {/if}

              {#if (detailStreams?.time_series?.latlng && detailStreams.time_series.latlng.length > 1) || detailStravaPolyline}
                <div class="mt-4">
                  <GpsTrace
                    latlng={detailStreams?.time_series?.latlng}
                    polyline={detailStravaPolyline}
                    velocity={detailStreams?.time_series?.velocity_smooth}
                    heartrate={detailStreams?.time_series?.heartrate}
                    zones={detailZones?.zones}
                    moving={detailStreams?.time_series?.moving}
                  />
                </div>
              {/if}

              {#if selectedWorkout.sport === 'row' && detailIntervals?.intervals?.length}
                <div class="mt-4">
                  <IntervalsTable data={detailIntervals} />
                </div>
              {/if}
            {/if}
          {/if}
        </Card>
      {:else}
        <div class="flex flex-col gap-2.5">
          <!-- Week selector -->
          <Card style="padding: 12px 14px;">
            <div class="flex flex-col gap-3 min-w-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.08em]">Week</p>
                <p class="text-[13px] font-semibold break-words">
                  {format(selectedWeekStart, 'MMM d')} – {format(selectedWeekEnd, 'MMM d, yyyy')}
                </p>
              </div>

              <div class="flex items-center gap-2 min-w-0 w-full sm:w-auto sm:shrink-0 sm:max-w-full">
                <button
                  class="shrink-0 px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, -7), 'yyyy-MM-dd'))}
                  aria-label="Previous week"
                >
                  ←
                </button>

                <div class="min-w-0 flex-1 sm:flex-none sm:w-[160px]">
                  <DatePicker
                    id="training-history-week"
                    bind:value={weekPickerValue}
                    ariaLabel="Select week"
                    buttonClass="px-2 py-1 pr-2 rounded-lg border border-border bg-glass2 text-[11px] text-text1"
                  />
                </div>

                <button
                  class="shrink-0 whitespace-nowrap px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={jumpToCurrentWeek}
                  aria-label="Jump to current week"
                >
                  Today
                </button>

                <button
                  class="shrink-0 px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, 7), 'yyyy-MM-dd'))}
                  aria-label="Next week"
                >
                  →
                </button>
              </div>
            </div>
          </Card>

          {#if weekWorkouts.length === 0}
            <Card style="padding: 14px;">
              <p class="text-[12px] text-text2">No workouts logged in this week.</p>
            </Card>
          {/if}

          {#each weekWorkouts as w (w?.id ?? w?.started_at)}
            {@const strainVal = Number.isFinite(Number(w?.strain_score)) ? Math.round(Number(w.strain_score)) : null}
            {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
            <button class="text-left bg-transparent border-none p-0 cursor-pointer w-full" onclick={() => selectedWorkout = w}>
              <Card style="padding: 12px 14px;">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center text-[18px] {getWorkoutBg(w.sport)}">
                    {getWorkoutIcon(w.sport)}
                  </div>
                  <div class="flex-1">
                    <p class="text-[13px] font-semibold text-text0">
                      {w.title || (getWorkoutLabel(w.sport) + ' Session')}
                    </p>
                    <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(getDurationSecs(w) / 60)} min</p>
                  </div>
                  <div class="text-right flex flex-col gap-1">
                    <div>
                      <p class="text-[14px] font-bold tabular-nums" style:color={boundedScoreCssColor(strainVal, true)}>
                        {strainVal === null ? '--' : strainVal}
                      </p>
                      <p class="text-[9px] text-text2 font-mono">STRAIN</p>
                    </div>
                    <div>
                      <p
                        class="text-[14px] font-bold tabular-nums"
                        style:color={boundedScoreCssColor(tssVal === null ? null : strainVal, true)}
                      >
                        {tssVal === null ? '--' : tssVal}
                      </p>
                      <p class="text-[9px] text-text2 font-mono">TSS</p>
                    </div>
                  </div>
                </div>
              </Card>
            </button>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>
