<script module lang="ts">
  import { SvelteMap, SvelteSet } from 'svelte/reactivity';

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
  import { weeklyTssTarget } from '$lib/utils/weeklyTarget';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { page } from '$app/stores';
  import { addDays, endOfWeek, format, startOfWeek } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import {
    mergeWorkoutZoneDefs,
    HR_ZONE_HEX,
    formatZoneBpmRange,
    canonicalHrZoneShortName,
  } from '$lib/hrZoneDisplay';
  import { CHART_ATL_STROKE, CHART_CTL_STROKE, formCssColor, getWeeklyLoadDeltaColor } from '$lib/scoreColors';
  import { Lightbulb } from '@lucide/svelte';
  import {
    getActivityDetail,
    hydrateActivityStreams,
    refetchWorkoutFromStrava,
    streamsHaveVelocity,
    streamsHaveHeartrate,
    type ActivityStreams,
    type ActivityLap,
    type ActivityIntervals,
    type ActivityZones,
  } from '$lib/services/activityService';
  import {
    loadWorkoutDetailCache,
    saveWorkoutDetailToCache,
    clearWorkoutDetailFromCache,
    preloadWorkoutDetail,
  } from '$lib/stores/workoutDetailCache';
  import { formatWorkoutDistance, normalizeUnits } from '$lib/utils/units';
  import { supportsPaceChart } from '$lib/utils/paceChart';
  import { intervalsToSplits, lapsToSplits } from '$lib/utils/lapSplits';
  import StreamCharts from '$lib/components/workout/StreamCharts.svelte';
  import SplitCharts from '$lib/components/workout/SplitCharts.svelte';
  import IntervalsTable from '$lib/components/workout/IntervalsTable.svelte';
  import GpsTrace from '$lib/components/workout/GpsTrace.svelte';
  import LapStrip from '$lib/components/workout/LapStrip.svelte';
  import DataSources from '$lib/components/workout/DataSources.svelte';
  import AddActivityModal from '$lib/components/AddActivityModal.svelte';

  const CTL_IDENTITY_HEX = CHART_CTL_STROKE;
  const ATL_IDENTITY_HEX = CHART_ATL_STROKE;

  let addActivityOpen = $state(false);
  let editActivityOpen = $state(false);
  let editingWorkout = $state<any>(null);

  const measurementUnitsForModal = $derived(
    (athleteStore.profile as any)?.measurement_units === 'imperial' ? 'imperial' : 'metric'
  );

  async function handleActivitySaved(payload: object) {
    await athleteStore.addWorkout(payload);
  }

  async function handleActivityUpdated(payload: object) {
    const workoutId = editingWorkout?.id ?? selectedWorkout?.id;
    if (!workoutId) throw new Error('No workout selected');

    const result = await athleteStore.updateWorkout(workoutId, payload);
    if (!result) throw new Error('Failed to update workout');

    if (typeof result === 'object') {
      const updated = { ...selectedWorkout, ...result };
      selectedWorkout = updated;
      editingWorkout = updated;
      return;
    }

    const match = (athleteStore.workouts || []).find((w) => String(w?.id) === String(workoutId));
    if (match) {
      selectedWorkout = match;
      editingWorkout = match;
    }
  }

  let metric = $state('history');
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
  $effect(() => {
    const workouts = athleteStore.workouts;
    if (!workouts?.length) return;

    // Background preload the most recent workout
    const latest = [...workouts].sort(
      (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
    )[0];
    if (latest?.id) {
      void preloadWorkoutDetail(latest.id);
    }
  });

  function onWorkoutCardIntent(workoutId: string) {
    void preloadWorkoutDetail(workoutId);
  }

  let workoutAnalysisText = $state<string | null>(null);
  let workoutAnalysisLoading = $state(false);

  let detailStreams = $state<ActivityStreams | null>(null);
  let detailLaps = $state<ActivityLap[]>([]);
  let detailIntervals = $state<ActivityIntervals | null>(null);
  let detailZones = $state<ActivityZones | null>(null);
  let detailLoading = $state(false);
  let detailHydrating = $state(false);
  let detailError = $state<string | null>(null);
  let detailRepulling = $state(false);
  let detailReloadEpoch = $state(0);
  let lastRepullWorkoutId = $state<string | null>(null);
  let repullDismissedWorkoutIds = new SvelteSet<string>();

  const mergedHrZoneDefs = $derived(
    mergeWorkoutZoneDefs(detailZones?.zones, athleteStore.profile?.hr_zones?.zones)
  );

  const measurementUnits = $derived(
    normalizeUnits((athleteStore.profile as { measurement_units?: string })?.measurement_units)
  );

  function hasActivityDetailSource(w: any): boolean {
    return Boolean(w?.id);
  }


  /** True when streams/laps/intervals loaded enough for the detail charts to render. */
  const detailChartsReady = $derived.by(() => {
    const w = selectedWorkout;
    if (!hasActivityDetailSource(w) || detailLoading || detailRepulling) {
      return false;
    }
    if (detailError) return false;

    const hasHrStream = (detailStreams?.time_series?.heartrate?.length ?? 0) > 1;
    const hasRoute = (detailStreams?.time_series?.latlng?.length ?? 0) > 1;
    const hasIntervals = (detailIntervals?.intervals?.length ?? 0) >= 2;

    if (w.sport === 'row') {
      return hasIntervals && (hasHrStream || hasRoute);
    }
    return hasHrStream || hasRoute || detailLaps.length >= 2;
  });

  const showRepullDataButton = $derived.by(() => {
    const w = selectedWorkout;
    if (!w?.strava_activity_id) return false;
    if (repullDismissedWorkoutIds.has(w.id)) return false;
    if (detailLoading) return false;
    if (detailRepulling) return true;
    return !detailChartsReady;
  });

  const detailMissingPaceStream = $derived(
    Boolean(selectedWorkout && supportsPaceChart(selectedWorkout.sport)) &&
      Boolean(detailStreams) &&
      !streamsHaveVelocity(detailStreams) &&
      (detailStreams?.time_series?.heartrate?.length ?? 0) > 1
  );

  const detailSplits = $derived.by(() => {
    const w = selectedWorkout;
    if (!w) return { splits: [], source: 'laps' as string };
    const sport = w.sport ?? '';
    if (sport === 'row' && (detailIntervals?.intervals?.length ?? 0) > 0) {
      return {
        splits: intervalsToSplits(detailIntervals!.intervals),
        source: detailIntervals?.source ?? 'laps',
      };
    }
    if (detailLaps.length >= 2) {
      return {
        splits: lapsToSplits(detailLaps, sport, measurementUnits),
        source: 'laps',
      };
    }
    return { splits: [], source: 'laps' };
  });

  /** Lap bar charts only when streams lack per-second HR or pace/speed. */
  const hasPerSecondStreamCharts = $derived(
    Boolean(detailStreams) &&
      (streamsHaveHeartrate(detailStreams) || streamsHaveVelocity(detailStreams))
  );

  const showLapSplitCharts = $derived(
    detailSplits.splits.length >= 2 &&
      !hasPerSecondStreamCharts &&
      (selectedWorkout?.sport === 'row' ||
        selectedWorkout?.sport === 'run' ||
        selectedWorkout?.sport === 'bike')
  );

  const showSplitsTable = $derived(
    detailSplits.splits.length >= 2 &&
      (selectedWorkout?.sport === 'row' ||
        selectedWorkout?.sport === 'run' ||
        selectedWorkout?.sport === 'bike')
  );

  $effect(() => {
    const w = selectedWorkout;
    if (
      !w?.id ||
      w.id !== lastRepullWorkoutId ||
      !detailChartsReady ||
      detailRepulling ||
      detailLoading
    ) {
      return;
    }
    repullDismissedWorkoutIds.add(w.id);
    lastRepullWorkoutId = null;
  });

  // Week selector (History tab)
  // Source of truth is the picked day (YYYY-MM-DD). We derive the Monday week start from it.
  let weekPickerValue = $state(format(new Date(), 'yyyy-MM-dd'));

  function openWorkout(w: { id?: string; started_at?: string }) {
    if (!w?.id) return;
    metric = 'history';
    if (w.started_at) {
      weekPickerValue = format(new Date(w.started_at), 'yyyy-MM-dd');
    }
    const target = resolve(`/training?workout_id=${encodeURIComponent(String(w.id))}`);
    if ($page.url.searchParams.get('workout_id') === String(w.id)) {
      const match = (athleteStore.workouts || []).find((x) => String(x?.id) === String(w.id));
      if (match) selectedWorkout = match;
      return;
    }
    goto(target, { keepFocus: true, noScroll: true, replaceState: true });
  }

  function closeWorkout() {
    if ($page.url.searchParams.has('workout_id')) {
      goto(resolve('/training'), { keepFocus: true, noScroll: true });
    } else {
      selectedWorkout = null;
    }
  }

  function parseDateInputLocal(value: string): Date {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!m) {
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
    }
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

  /** Keep detail view in sync with ?workout_id= (deep links, Training tab, browser back). */
  $effect(() => {
    const id = workoutIdFromUrl;
    if (!id) {
      selectedWorkout = null;
      return;
    }
    if (!hasWorkouts) return;

    const match = (athleteStore.workouts || []).find((w) => String(w?.id) === String(id));
    if (!match) return;

    metric = 'history';
    weekPickerValue = format(new Date(match.started_at), 'yyyy-MM-dd');
    selectedWorkout = match;
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
    if (t === 'mobility') return '#a855f7'; // sport-type color, no design token
    if (t === 'other') return 'var(--amber)';
    return 'var(--text2)';
  }

  function getWorkoutBg(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run' || t === 'running') return 'bg-blue-dim border-blue-glow';
    if (t === 'bike' || t === 'cycling') return 'bg-teal-dim border-teal/30';
    if (t === 'row' || t === 'rowing') return 'bg-amber-dim border-amber/30';
    if (t === 'mobility') return 'bg-glass border-[rgba(168,85,247,0.35)]';
    if (t === 'other') return 'bg-glass border-[rgba(234,179,8,0.35)]';
    return 'bg-glass border-border';
  }

  /** TSS from workouts started in the last 7 days — source of truth for the Weekly TSS card. */
  const weeklyTss = $derived.by(() => {
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return (athleteStore.workouts || [])
      .filter((w: any) => w?.started_at && new Date(w.started_at).getTime() >= cutoff)
      .reduce((acc: number, w: any) => acc + (w.tss || 0), 0);
  });

  /** Oldest→newest daily rows for baseline math */
  const trainingLoadSorted = $derived.by(() =>
    [...(athleteStore.metrics?.trainingLoadData ?? [])]
      .filter((r: any) => r?.date)
      .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
  );

  /** Current week TSS vs mean of prior (up to six) trailing 7-day windows from tss_history. */
  const weeklyRollingContext = $derived.by(() => {
    const rows = trainingLoadSorted;
    const n = rows.length;
    const sumWindowEnding = (endEx: number) => {
      if (endEx < 7) return null as number | null;
      let s = 0;
      for (let i = endEx - 7; i < endEx; i++) s += Number((rows[i] as any)?.daily_tss ?? 0);
      return s;
    };

    // weekSum always comes from actual workouts so it's never sourced from stale tss_history.
    // Historical baseline/delta still use tss_history rows which represent longer-term trends.
    if (n >= 14) {
      const historics: number[] = [];
      for (let end = n - 7; end >= 14 && historics.length < 8; end -= 7) {
        const v = sumWindowEnding(end);
        if (v != null) historics.push(v);
      }
      if (historics.length > 0) {
        const baseline = historics.reduce((a, b) => a + b, 0) / historics.length;
        const delta = weeklyTss - baseline;
        const pct = delta / Math.max(baseline, 1e-6);
        return {
          weekSum: Math.round(weeklyTss),
          baseline: Math.round(baseline),
          delta: Math.round(delta),
          pct
        };
      }
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

  function formatAvgPower(w: any): string {
    const raw = w?.avg_power_w ?? w?.average_watts;
    if (raw == null) return '--';
    const watts = Number(raw);
    return Number.isFinite(watts) ? String(Math.round(watts)) : '--';
  }

  function formatMMSS(totalSeconds: number): string {
    const s = Math.max(0, Math.floor(totalSeconds || 0));
    const m = Math.floor(s / 60);
    const ss = String(s % 60).padStart(2, '0');
    return `${m}:${ss}`;
  }

  function getHrZonePcts(w: any): Array<number | null> {
    return [
      w?.hr_zone_1_pct ?? null,
      w?.hr_zone_2_pct ?? null,
      w?.hr_zone_3_pct ?? null,
      w?.hr_zone_4_pct ?? null,
      w?.hr_zone_5_pct ?? null
    ].map((v) => (v == null ? null : Number(v)));
  }

  function getHrZonePctsTopDown(w: any): Array<number | null> {
    // Display order: Z5 (top) → Z1 (bottom); Astraphe model is always Z1–Z5 (no WHOOP Z0 bucket).
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
      closeWorkout();
    } catch (e) {
      console.error(e);
      alert('Failed to delete workout');
    }
  }

  function openEditActivity() {
    if (!selectedWorkout?.id) return;
    editingWorkout = selectedWorkout;
    editActivityOpen = true;
  }

  function closeEditActivityModal() {
    editActivityOpen = false;
    editingWorkout = null;
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

  async function repullWorkoutData() {
    const w = selectedWorkout;
    if (!w?.id || !w.strava_activity_id || detailRepulling) return;
    detailRepulling = true;
    detailError = null;
    lastRepullWorkoutId = w.id;
    try {
      const result = await refetchWorkoutFromStrava(w.id);
      if (result.workout) {
        selectedWorkout = { ...w, ...result.workout };
        clearWorkoutDetailFromCache(w.id);
      }
      detailReloadEpoch += 1;
    } catch (e: unknown) {
      detailError = e instanceof Error ? e.message : 'Failed to repull workout data';
    } finally {
      detailRepulling = false;
    }
  }

  $effect(() => {
    const w = selectedWorkout;
    void detailReloadEpoch;

    detailError = null;
    detailLoading = false;
    detailHydrating = false;

    if (!hasActivityDetailSource(w)) {
      detailStreams = null;
      detailLaps = [];
      detailIntervals = null;
      detailZones = null;
      return;
    }

    let cancelled = false;

    // SWR: Try cache first
    const cache = loadWorkoutDetailCache();
    const cached = cache[w.id];
    if (cached) {
      detailStreams = cached.streams;
      detailLaps = cached.laps ?? [];
      detailIntervals = cached.intervals;
      detailZones = cached.zones;
      // We still "load" in background, but don't show the skeleton if we have cached data
    } else {
      detailStreams = null;
      detailLaps = [];
      detailIntervals = null;
      detailZones = null;
      detailLoading = true;
    }

    (async () => {
      try {
        let detail = await getActivityDetail(w.id);
        if (cancelled) return;

        detailStreams = detail.streams;
        detailLaps = detail.laps ?? [];
        detailIntervals = detail.intervals;
        detailZones = detail.zones;
        detailLoading = false;

        if (
          !detail.streams &&
          w.strava_activity_id &&
          w.strava_streams_fetched === false
        ) {
          detailHydrating = true;
          try {
            const hydrated = await hydrateActivityStreams(w.id);
            if (cancelled) return;
            if (hydrated.status === 'hydrated' || hydrated.status === 'already_stored') {
              detail = await getActivityDetail(w.id);
              if (cancelled) return;
              detailStreams = detail.streams;
              detailLaps = detail.laps ?? [];
              detailIntervals = detail.intervals;
              detailZones = detail.zones;
              clearWorkoutDetailFromCache(w.id);
            }
          } finally {
            if (!cancelled) detailHydrating = false;
          }
        }

        if (cancelled) return;

        saveWorkoutDetailToCache(w.id, {
          streams: detail.streams,
          laps: detail.laps ?? [],
          intervals: detail.intervals,
          zones: detail.zones,
        });
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

  // --- Design view: Log (this week + activities) ---
  const isCurrentWeek = $derived(format(selectedWeekStart, "yyyy-MM-dd") === format(startOfWeek(new Date(), { weekStartsOn: 1 }), "yyyy-MM-dd"));
  const weekRangeLabel = $derived(
    format(selectedWeekStart, "MMM") === format(selectedWeekEnd, "MMM")
      ? `${format(selectedWeekStart, "d")} – ${format(selectedWeekEnd, "d MMM")}`
      : `${format(selectedWeekStart, "d MMM")} – ${format(selectedWeekEnd, "d MMM")}`
  );
  const weeklyTarget = $derived(weeklyTssTarget(athleteStore.ctl, Number((athleteStore.profile as any)?.weekly_tss_target) || null) ?? 0);
  const weekTotals = $derived.by(() => {
    let tss = 0, secs = 0, meters = 0;
    for (const w of weekWorkouts as any[]) {
      tss += Number(w?.tss) || 0;
      secs += getDurationSecs(w);
      meters += Number(w?.distance_m) || 0;
    }
    const imperial = measurementUnits === "imperial";
    const dist = imperial ? meters / 1609.344 : meters / 1000;
    const h = Math.floor(secs / 3600);
    const m = Math.round((secs % 3600) / 60);
    return {
      tss: Math.round(tss),
      time: h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`,
      distance: dist >= 100 ? String(Math.round(dist)) : String(Math.round(dist * 10) / 10),
      distanceUnit: imperial ? "mi" : "km"
    };
  });
  const SPORT_GLYPHS: Record<string, string> = { bike: "BIKE", cycling: "BIKE", run: "RUN", running: "RUN", swim: "SWIM", swimming: "SWIM", strength: "GYM", gym: "GYM", row: "ROW", rowing: "ROW", mobility: "MOB" };
  const sportGlyph = (sport: string) => SPORT_GLYPHS[String(sport ?? "").toLowerCase()] ?? "OTHER";
  function activityMeta(w: any): string {
    const parts: string[] = [];
    const d = w?.started_at ? new Date(w.started_at) : null;
    if (d && !Number.isNaN(d.getTime())) parts.push(format(d, "EEE d MMM"));
    const secs = getDurationSecs(w);
    if (secs > 0) { const h = Math.floor(secs / 3600); const m = Math.round((secs % 3600) / 60); parts.push(h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`); }
    const meters = Number(w?.distance_m) || 0;
    if (meters > 0) parts.push(measurementUnits === "imperial" ? `${(meters / 1609.344).toFixed(1)} mi` : `${(meters / 1000).toFixed(1)} km`);
    const np = Number(w?.norm_power_w) || 0;
    if (np > 0) parts.push(`${np} W NP`);
    return parts.join(" · ");
  }
  const loadInsight = $derived.by(() => {
    const ctx = weeklyRollingContext;
    if (!ctx || ctx.baseline == null || ctx.pct == null) return null;
    const pct = Math.round(Math.abs(ctx.pct) * 100);
    return `This week is ${ctx.weekSum} TSS so far, ${pct}% ${ctx.pct >= 0 ? "above" : "below"} your recent average of ${ctx.baseline}.`;
  });

  $effect(() => {
    pageHeader.eyebrow = weekRangeLabel;
    pageHeader.add = () => (addActivityOpen = true);
    pageHeader.addLabel = "Log activity";
    return resetPageHeader;
  });
</script>

{#if addActivityOpen}
  <AddActivityModal
    show={addActivityOpen}
    onClose={() => (addActivityOpen = false)}
    units={measurementUnitsForModal}
    onSaved={handleActivitySaved}
  />
{/if}

{#if editActivityOpen}
  <AddActivityModal
    show={editActivityOpen}
    mode="edit"
    workout={editingWorkout}
    onClose={closeEditActivityModal}
    units={measurementUnitsForModal}
    onSaved={handleActivityUpdated}
  />
{/if}

<div class="flex flex-col gap-3">
  {#if showNoTrainingData}
    <EmptyState
      title="No Training Data"
      message="Connect your training apps to analyze your performance trends and history."
      secondaryLabel="Log Activity"
      onSecondaryAction={() => (addActivityOpen = true)}
    />
  {:else if !hasWorkouts}
    <EmptyState 
      title="Waiting for Workouts" 
      message="We're waiting for your training history to sync from your connected services."
      icon="⏳"
    />
  {:else}
    {#if metric === 'history'}
      {#if selectedWorkout}
        <!-- Detailed Workout View -->
        <div class="mb-2 flex items-center justify-between gap-2">
          <button
            class="text-xs text-blue flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer"
            onclick={closeWorkout}
          >
            ← Back to list
          </button>

          <div class="flex items-center gap-3">
            <button
              class="text-xs text-blue bg-transparent border-none p-0 cursor-pointer"
              onclick={openEditActivity}
            >
              Edit
            </button>
            <button
              class="text-xs text-red bg-transparent border-none p-0 cursor-pointer"
              onclick={deleteSelectedWorkout}
            >
              Delete
            </button>
          </div>
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

          <div class="grid grid-cols-2 gap-2 mb-5">
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Duration</p>
              <p class="text-sm font-bold">{Math.floor(getDurationSecs(selectedWorkout) / 60)}m</p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Distance</p>
              <p class="text-sm font-bold">
                {formatWorkoutDistance(selectedWorkout.distance_m, measurementUnits, selectedWorkout.sport)}
              </p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Avg HR</p>
              <p class="text-sm font-bold">{selectedWorkout.avg_hr || '--'} <span class="text-[10px] font-normal opacity-60">bpm</span></p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Avg Watts</p>
              <p class="text-sm font-bold">
                {formatAvgPower(selectedWorkout)}
                {#if formatAvgPower(selectedWorkout) !== '--'}
                  <span class="text-[10px] font-normal opacity-60">w</span>
                {/if}
              </p>
            </div>
          </div>

          <div class="mb-5 min-w-0 bg-glass2 p-3 rounded-xl border border-border">
            <p class="text-[11px] font-semibold mb-2">Heart-rate zones</p>

            {#if hasAnyHrZone(selectedWorkout)}
              <div class="flex w-full min-w-0 flex-col gap-2">
                {#each getHrZonePctsTopDown(selectedWorkout) as pct, topIdx (topIdx)}
                  {@const zone = 5 - topIdx}
                  {@const color = HR_ZONE_HEX[zone]}
                  {@const zDef = mergedHrZoneDefs.find((d) => d.zone === zone)}
                  {@const zn = canonicalHrZoneShortName(zone) || zDef?.name}
                  <div class="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-1.5 gap-y-1.5">
                    <div class="flex min-w-0 gap-2 self-start pt-0.5">
                      <span class="mt-1 h-2 w-2 shrink-0 rounded-full" style="background: {color};"></span>
                      <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span class="text-[11px] text-text0 font-mono uppercase shrink-0">Z{zone}</span>
                          {#if zn}
                            <span class="text-[11px] text-text1 font-sans font-medium leading-snug">{zn}</span>
                          {/if}
                          <span class="text-[10px] text-text2 font-mono">{formatZoneBpmRange(zDef)}</span>
                        </div>
                      </div>
                    </div>
                    <p class="self-start text-right text-[11px] font-mono tabular-nums leading-none text-text2">
                      {pct == null ? '--' : `${Math.round(pct)}%`}
                    </p>
                    <div
                      class="h-2.5 min-w-0 w-full max-w-full self-center overflow-hidden rounded-full border border-border bg-glass"
                    >
                      <div
                        class="h-full max-w-full rounded-full"
                        style="width: {pct == null ? 0 : Math.max(0, Math.min(100, pct))}%; background: {color};"
                      ></div>
                    </div>
                    <p class="self-center text-right text-[11px] font-semibold tabular-nums leading-none text-text1">
                      {pct == null ? '--' : formatMMSS((getDurationSecs(selectedWorkout) * pct) / 100)}
                    </p>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-[11px] text-text2">No zone data for this workout</p>
            {/if}
          </div>

          {#if authStore.tier === 'premium'}
            <div class="mt-4 pt-4 border-t border-border/40 rounded-xl p-3 bg-bg1">
              <div class="flex items-center gap-1.5 mb-2">
                <span class="text-[11px] font-mono uppercase tracking-[0.08em] text-blue">AI Insight</span>
                <Tag color="var(--blue)">ASTRAPHE</Tag>
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

          {#if hasActivityDetailSource(selectedWorkout)}
            {#if showRepullDataButton}
              <div class="mt-3">
                <button
                  type="button"
                  class="px-3 py-1.5 rounded-full text-[11px] font-medium border border-border bg-glass2 text-text1 hover:border-teal/40 hover:text-teal transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  disabled={detailRepulling || detailLoading}
                  onclick={() => repullWorkoutData()}
                >
                  {detailRepulling ? 'Pulling data…' : 'Repull data'}
                </button>
              </div>
            {/if}

            {#if detailLoading}
              <div class="mt-4 space-y-3">
                {#each [{ id: 'streams', h: 150 }, { id: 'map', h: 150 }, { id: 'splits', h: 120 }] as skeleton (skeleton.id)}
                  <div class="rounded-2xl bg-glass animate-pulse" style="height: {skeleton.h}px;"></div>
                {/each}
              </div>

            {:else if detailError}
              <p class="text-[11px] text-red mt-3 font-mono">{detailError}</p>

            {:else}
              {#if selectedWorkout.strava_activity_id && selectedWorkout.strava_streams_fetched === false && !detailHydrating && !detailStreams}
                <p class="text-[11px] text-text2 font-mono mt-3 leading-relaxed">
                  Strava is linked, but stream data has not been imported for this workout yet. Reconnect
                  Strava or run the Strava backfill script to load charts and GPS.
                </p>
              {:else if !detailStreams && !detailHydrating}
                <p class="text-[11px] text-text2 font-mono mt-3">
                  No stream data stored for this workout.
                </p>
              {/if}

              {#if detailLaps.length >= 2}
                <div class="mt-4">
                  <LapStrip
                    laps={detailLaps}
                    sport={selectedWorkout.sport}
                    zones={mergedHrZoneDefs}
                    measurementUnits={measurementUnits}
                  />
                </div>
              {/if}

              {#if detailMissingPaceStream}
                <p class="text-[11px] text-text2 font-mono mt-3 leading-relaxed">
                  Pace stream unavailable for this activity (heart rate is still shown). Try
                  refreshing imported data if streams were imported incorrectly.
                </p>
              {/if}

              {#if detailHydrating && !detailStreams}
                <div class="mt-4 space-y-2">
                  <div class="rounded-2xl bg-glass animate-pulse" style="height: 150px;"></div>
                  <p class="text-[11px] text-text2 font-mono animate-pulse">
                    Loading stream data…
                  </p>
                </div>
              {:else if detailStreams}
                <div class="mt-4 min-h-[260px]">
                  <StreamCharts
                    streams={detailStreams}
                    laps={detailLaps}
                    sport={selectedWorkout.sport}
                    zones={mergedHrZoneDefs}
                    measurementUnits={measurementUnits}
                  />
                </div>
              {/if}

              {#if detailStreams?.time_series?.latlng && detailStreams.time_series.latlng.length > 1}
                <div class="mt-4 min-h-[300px]">
                  <GpsTrace
                    latlng={detailStreams.time_series.latlng}
                    heartrate={detailStreams?.time_series?.heartrate}
                    time={detailStreams?.time_series?.time}
                    zones={mergedHrZoneDefs}
                  />
                </div>
              {/if}

              {#if showLapSplitCharts}
                <div class="mt-4 w-full">
                  <SplitCharts
                    splits={detailSplits.splits}
                    sport={selectedWorkout.sport}
                    zones={mergedHrZoneDefs}
                    measurementUnits={measurementUnits}
                    source={detailSplits.source}
                  />
                </div>
              {/if}

              {#if showSplitsTable}
                <div class="mt-4 w-full">
                  <IntervalsTable
                    splits={detailSplits.splits}
                    sport={selectedWorkout.sport}
                    source={detailSplits.source}
                    measurementUnits={measurementUnits}
                  />
                </div>
              {/if}
            {/if}
          {/if}
        </Card>
      {:else}
        <div class="flex flex-col gap-3.5">
          <!-- This week -->
          <section aria-label="This week" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3.5">
            <div class="flex justify-between items-center">
              <button type="button" aria-label="Previous week" class="w-11 h-8 border-0 bg-transparent text-text2 flex items-center justify-start p-0 cursor-pointer"
                onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, -7), 'yyyy-MM-dd'))}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
              </button>
              <div class="flex items-center gap-1.5">
                <div class="min-w-[120px]">
                  <DatePicker bind:value={weekPickerValue} label={weekRangeLabel} hideChevron ariaLabel="Select week" buttonClass="h-8 px-2 justify-center gap-1.5 rounded-[10px] bg-transparent border-0 text-[14px] font-medium text-text0" popoverClass="!left-auto !right-1/2 translate-x-1/2" />
                </div>
                {#if !isCurrentWeek}
                  <button type="button" class="h-8 px-2.5 rounded-[10px] border border-border bg-transparent text-xs font-medium text-text0 cursor-pointer" onclick={jumpToCurrentWeek}>Today</button>
                {/if}
              </div>
              <button type="button" aria-label="Next week" disabled={isCurrentWeek} class="w-11 h-8 border-0 bg-transparent flex items-center justify-end p-0 {isCurrentWeek ? 'text-text2/40 cursor-not-allowed' : 'text-text2 cursor-pointer'}"
                onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, 7), 'yyyy-MM-dd'))}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
              </button>
            </div>
            <div class="grid grid-cols-3 gap-2">
              <div class="flex flex-col gap-0.5"><span class="text-[22px] font-medium tracking-[-0.02em]">{weekTotals.tss}{#if weeklyTarget}<span class="text-xs text-text2 font-normal"> / {weeklyTarget}</span>{/if}</span><span class="text-[11px] text-text2">TSS</span></div>
              <div class="flex flex-col gap-0.5"><span class="text-[22px] font-medium tracking-[-0.02em]">{weekTotals.time}</span><span class="text-[11px] text-text2">Time</span></div>
              <div class="flex flex-col gap-0.5"><span class="text-[22px] font-medium tracking-[-0.02em]">{weekTotals.distance}<span class="text-xs text-text2 font-normal"> {weekTotals.distanceUnit}</span></span><span class="text-[11px] text-text2">Distance</span></div>
            </div>
            {#if weeklyTarget}
              <div aria-hidden="true" class="h-1.5 rounded-[3px] bg-border overflow-hidden"><div class="h-1.5 rounded-[3px] bg-blue" style="width: {Math.min(100, Math.round((weekTotals.tss / weeklyTarget) * 100))}%"></div></div>
            {/if}
          </section>

          <!-- Activities -->
          <section aria-label="Activities" class="flex flex-col gap-2">
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2">{isCurrentWeek ? 'RECENT ACTIVITIES' : 'ACTIVITIES'}</span>
            {#if weekWorkouts.length === 0}
              <div class="px-4 py-3.5 rounded-[18px] bg-bg1 border border-border text-[13px] text-text2">No workouts logged in this week.</div>
            {/if}
            {#each weekWorkouts as w, i (w?.id ?? w?.started_at)}
              {@const tssVal = Number.isFinite(Number(w?.tss)) && Number(w.tss) > 0 ? Math.round(Number(w.tss)) : null}
              <button
                type="button"
                class="flex items-center gap-3 px-3.5 py-3 rounded-[18px] bg-bg1 border border-border text-left w-full cursor-pointer"
                onclick={() => openWorkout(w)}
                onmouseenter={() => w.id && onWorkoutCardIntent(w.id)}
                ontouchstart={() => w.id && onWorkoutCardIntent(w.id)}
              >
                <span aria-hidden="true" class="shrink-0 w-10 h-10 rounded-xl flex items-center justify-center font-mono text-[11px] font-medium {i === 0 && isCurrentWeek ? 'bg-blue-dim text-blue' : 'bg-bg3 text-text1'}">{sportGlyph(w.sport)}</span>
                <span class="flex-1 min-w-0 flex flex-col gap-0.5">
                  <span class="text-sm font-medium truncate">{w.title || (getWorkoutLabel(w.sport) + ' Session')}</span>
                  <span class="text-xs text-text2 truncate">{activityMeta(w)}</span>
                </span>
                <span class="flex flex-col items-end gap-0.5">
                  <span class="font-mono text-[13px]">{tssVal ?? '—'}</span>
                  <span class="text-[11px] text-text2">TSS</span>
                </span>
              </button>
            {/each}
          </section>

          {#if loadInsight}
            <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-border">
              <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">LOAD</span>
              <span class="text-[13px] leading-[1.45] text-text1">{loadInsight}</span>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  {/if}
</div>
