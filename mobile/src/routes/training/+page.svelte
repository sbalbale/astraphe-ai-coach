<script module lang="ts">
  import { SvelteMap, SvelteSet } from 'svelte/reactivity';

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
  import WeekNavigator from '$lib/components/WeekNavigator.svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
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
  import { formatElevationMeters, formatWorkoutDistance, normalizeUnits } from '$lib/utils/units';
  import { supportsPaceChart } from '$lib/utils/paceChart';
  import { intervalsToSplits, lapsToSplits } from '$lib/utils/lapSplits';
  import StreamCharts from '$lib/components/workout/StreamCharts.svelte';
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


  const showSplitsTable = $derived(detailSplits.splits.length >= 2);

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
    // Push the detail on top of the list, so Back (incl. Android's) returns to the list.
    openedFromList = true;
    goto(target, { keepFocus: true, noScroll: true });
  }

  // True when this page pushed the detail entry itself (vs. arriving on a deep link).
  let openedFromList = false;

  function closeWorkout() {
    if ($page.url.searchParams.has('workout_id')) {
      if (openedFromList && typeof history !== 'undefined' && history.length > 1) {
        // Pop the entry we pushed: closing then Back no longer reopens the workout.
        openedFromList = false;
        history.back();
      } else {
        goto(resolve('/training'), { keepFocus: true, noScroll: true, replaceState: true });
      }
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

  // (An AI analysis used to be requested here on every change and never shown,
  // costing an LLM generation per view. Removed.)

  // --- Design view: Log (this week + activities) ---
  const isCurrentWeek = $derived(format(selectedWeekStart, "yyyy-MM-dd") === format(startOfWeek(new Date(), { weekStartsOn: 1 }), "yyyy-MM-dd"));
  const weekRangeLabel = $derived(
    format(selectedWeekStart, "MMM") === format(selectedWeekEnd, "MMM")
      ? `${format(selectedWeekStart, "d")} – ${format(selectedWeekEnd, "d MMM")}`
      : `${format(selectedWeekStart, "d MMM")} – ${format(selectedWeekEnd, "d MMM")}`
  );
  // Calculated by the backend (calculate_weekly_tss_target) and stored on the athlete.
  const weeklyTarget = $derived(Number((athleteStore.profile as any)?.weekly_tss_target) || 0);
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

  // --- Workout detail (design) ---
  let detailTab = $state('overview');
  let showAllSplits = $state(false);
  $effect(() => { void selectedWorkout?.id; detailTab = 'overview'; showAllSplits = false; });
  // Splits table cells (units live in the column, not the cell).
  function splitTime(secs: number): string {
    const t = Math.max(0, Math.round(Number(secs) || 0));
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const ss = String(t % 60).padStart(2, "0");
    return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  }
  function splitDistance(meters: number): string {
    const m = Number(meters) || 0;
    if (m <= 0) return "—";
    return (measurementUnits === "imperial" ? m / 1609.344 : m / 1000).toFixed(m < 1000 ? 2 : 1);
  }
  function splitPace(secs: number | null): string {
    const p = Number(secs);
    if (!Number.isFinite(p) || p <= 0) return "—";
    return `${Math.floor(p / 60)}:${String(Math.round(p % 60)).padStart(2, "0")}`;
  }
  function splitSpeed(r: any): string {
    const v = Number(r?.average_speed) > 0 ? Number(r.average_speed) : Number(r?.distance) > 0 && Number(r?.elapsed_time) > 0 ? Number(r.distance) / Number(r.elapsed_time) : 0;
    if (v <= 0) return "—";
    return (measurementUnits === "imperial" ? v * 2.23694 : v * 3.6).toFixed(1);
  }
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
        <!-- Detailed Workout View (map hero + tabs) -->
        {@const sel = selectedWorkout}
        {@const selTss = Number.isFinite(Number(sel?.tss)) && Number(sel.tss) > 0 ? Math.round(Number(sel.tss)) : null}
        {@const selStrain = Number.isFinite(Number(sel?.strain_score)) && Number(sel.strain_score) > 0 ? Math.round(Number(sel.strain_score)) : null}
        {@const selSecs = getDurationSecs(sel)}
        {@const selNp = Number(sel?.norm_power_w) || 0}
        {@const selLatlng = detailStreams?.time_series?.latlng}
        {@const selLthr = Number((athleteStore.profile as any)?.lthr ?? (athleteStore.profile as any)?.threshold_hr) || 0}
        {@const selElev = Number(sel?.elevation_gain_m) || 0}
        <div class="-mx-4 flex flex-col">
          <!-- Map hero -->
          <div class="relative">
            {#if selLatlng && selLatlng.length > 1}
              <GpsTrace
                hero
                latlng={selLatlng}
                heartrate={detailStreams?.time_series?.heartrate}
                time={detailStreams?.time_series?.time}
                zones={mergedHrZoneDefs}
              />
            {:else}
              <div class="h-[150px] bg-bg1 {detailLoading || detailHydrating ? 'animate-pulse' : ''}"></div>
            {/if}
            <div class="absolute left-4 right-4 top-4 z-10 flex justify-between pointer-events-none">
              <button type="button" aria-label="Back to training" class="pointer-events-auto w-11 h-11 rounded-full bg-bg0/85 border border-border text-text0 flex items-center justify-center cursor-pointer" onclick={closeWorkout}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
              </button>
              <div class="pointer-events-auto flex gap-1.5">
                <button type="button" aria-label="Edit workout" class="w-11 h-11 rounded-full bg-bg0/85 border border-border text-text0 flex items-center justify-center cursor-pointer" onclick={openEditActivity}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"></path><path d="m13 7 4 4"></path></svg>
                </button>
                <button type="button" aria-label="Delete workout" class="w-11 h-11 rounded-full bg-bg0/85 border border-border text-red flex items-center justify-center cursor-pointer" onclick={deleteSelectedWorkout}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
                </button>
              </div>
            </div>
          </div>

          <!-- Sheet -->
          <div class="relative -mt-6 px-5 pt-5 pb-10 rounded-t-[28px] bg-bg0 border-t border-border flex flex-col gap-3.5">
            <header class="flex justify-between items-start gap-3">
              <div class="flex flex-col gap-1.5 min-w-0">
                <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{getWorkoutLabel(sel.sport)} · {format(new Date(sel.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'EEE d MMM · HH:mm' : 'EEE d MMM · h:mm a')}</span>
                <h1 class="m-0 font-display font-normal text-[32px] leading-[1.05]">{sel.title || (getWorkoutLabel(sel.sport) + ' Session')}</h1>
              </div>
              <span class="shrink-0 flex gap-3 pt-[18px]">
                <span class="flex flex-col items-center"><span class="font-display text-[28px] leading-none">{selStrain ?? '--'}</span><span class="font-mono text-[9px] text-text2">STRAIN</span></span>
                <span class="flex flex-col items-center"><span class="font-display text-[28px] leading-none">{selTss ?? '--'}</span><span class="font-mono text-[9px] text-text2">TSS</span></span>
              </span>
            </header>

            <dl class="m-0 grid grid-cols-4 gap-1.5">
              {#each [
                { k: 'Duration', v: `${Math.floor(selSecs / 3600)}:${String(Math.floor((selSecs % 3600) / 60)).padStart(2, '0')} h` },
                { k: 'Distance', v: formatWorkoutDistance(sel.distance_m, measurementUnits, sel.sport) },
                { k: 'Avg HR', v: sel.avg_hr ? String(sel.avg_hr) : '--' },
                { k: 'Avg W', v: formatAvgPower(sel) }
              ] as stat (stat.k)}
                <div class="p-2.5 rounded-[14px] bg-bg2 flex flex-col-reverse gap-0.5">
                  <dt class="text-[10px] text-text2">{stat.k}</dt>
                  <dd class="m-0 text-[15px] font-medium truncate">{stat.v}</dd>
                </div>
              {/each}
            </dl>

            <div role="tablist" aria-label="Workout sections" class="grid grid-cols-4 gap-0.5 p-1 rounded-[14px] bg-bg2 border border-border">
              {#each [['overview', 'Overview'], ['charts', 'Charts'], ['laps', 'Laps'], ['data', 'Data']] as [id, label] (id)}
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailTab === id}
                  class="h-9 border-0 rounded-[10px] text-[13px] font-medium cursor-pointer {detailTab === id ? 'bg-bg3 text-text0' : 'bg-transparent text-text2'}"
                  onclick={() => (detailTab = id)}
                >{label}</button>
              {/each}
            </div>

            {#if detailTab === 'overview'}
              {#if authStore.tier === 'premium'}
                <section aria-label="Coach analysis" class="flex flex-col gap-2 p-4 rounded-[20px] bg-bg1 border border-dashed border-border">
                  <span class="font-mono text-[10px] tracking-[0.12em] text-blue">COACH ANALYSIS</span>
                  {#if workoutAnalysisLoading && !workoutAnalysisMemo.has(selectedWorkout.id)}
                    <p class="m-0 text-sm text-text2 animate-pulse">Analyzing workout…</p>
                  {:else}
                    <p class="m-0 text-sm leading-[1.5] text-text1">{workoutAnalysisMemo.get(selectedWorkout.id) ?? 'Insight unavailable.'}</p>
                  {/if}
                </section>
              {:else}
                <section aria-label="Analysis" class="flex flex-col gap-2 p-4 rounded-[20px] bg-bg1 border border-dashed border-border">
                  <span class="font-mono text-[10px] tracking-[0.12em] text-blue">ANALYSIS</span>
                  <p class="m-0 text-sm leading-[1.5] text-text1">
                    This session added {Math.round(selectedWorkout.tss || 0)} TSS to your acute load. {selectedWorkout.tss > 80 ? 'Make recovery a priority tonight.' : 'A good aerobic contribution.'}
                  </p>
                </section>
              {/if}

              <dl class="m-0 grid grid-cols-3 gap-2">
                {#each [
                  { k: 'Norm. power', v: selNp > 0 ? `${selNp} W` : '--' },
                  { k: 'Max HR', v: sel.max_hr ? String(sel.max_hr) : '--' },
                  { k: 'Elevation', v: selElev > 0 ? `+${formatElevationMeters(selElev, measurementUnits)}` : '--' }
                ] as stat (stat.k)}
                  <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5">
                    <dt class="text-[11px] text-text2">{stat.k}</dt>
                    <dd class="m-0 text-[17px] font-medium">{stat.v}</dd>
                  </div>
                {/each}
              </dl>

              <section aria-label="Heart-rate zones" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3">
                <div class="flex justify-between items-baseline">
                  <h2 class="m-0 font-display font-normal text-[22px]">Heart-rate zones</h2>
                  {#if selLthr}<span class="font-mono text-[11px] text-text2">LTHR {selLthr}</span>{/if}
                </div>
                {#if hasAnyHrZone(sel)}
                  {@const zp = getHrZonePcts(sel)}
                  <div aria-hidden="true" class="flex gap-[3px] h-2.5">
                    {#each zp as p, i (i)}
                      {#if (p ?? 0) > 0}<span class="rounded-[3px]" style="flex: {p} 1 0; min-width: 4px; background: var(--zone-{i + 1})"></span>{/if}
                    {/each}
                  </div>
                  <div class="flex flex-col">
                    {#each getHrZonePctsTopDown(sel) as pct, topIdx (topIdx)}
                      {@const zone = 5 - topIdx}
                      {@const zDef = mergedHrZoneDefs.find((d) => d.zone === zone)}
                      {@const zn = canonicalHrZoneShortName(zone) || zDef?.name}
                      <div class="grid grid-cols-[14px_1fr_auto_auto_auto] items-center gap-2.5 py-3 border-t border-border text-[15px]">
                        <span aria-hidden="true" class="h-2.5 w-2.5 rounded-[3px]" style="background: {HR_ZONE_HEX[zone]}"></span>
                        <span class="min-w-0 truncate"><span class="font-semibold">Z{zone}</span>{#if zn} <span class="text-text1">{zn}</span>{/if}</span>
                        <span class="font-mono text-xs text-text2">{formatZoneBpmRange(zDef)}</span>
                        <span class="w-9 text-right font-mono text-[13px] text-text1 tabular-nums">{pct == null ? '--' : `${Math.round(pct)}%`}</span>
                        <span class="w-12 text-right font-mono text-[13px] tabular-nums">{pct == null ? '--' : formatMMSS((selSecs * pct) / 100)}</span>
                      </div>
                    {/each}
                  </div>
                {:else}
                  <p class="m-0 text-[13px] text-text2">No zone data for this workout.</p>
                {/if}
              </section>
            {/if}

            {#if detailTab === 'charts'}
              {#if detailLoading || (detailHydrating && !detailStreams)}
                <div class="rounded-[24px] bg-bg2 animate-pulse" style="height: 220px;"></div>
              {:else if detailError}
                <p class="m-0 text-[11px] text-red font-mono">{detailError}</p>
              {:else if detailStreams}
                {#if detailMissingPaceStream}
                  <p class="m-0 text-[13px] text-text2 leading-relaxed px-1">Pace stream unavailable for this activity (heart rate is still shown). Try refreshing imported data if streams were imported incorrectly.</p>
                {/if}
                <section aria-label="Power and heart rate" class="bg-bg2 border border-border rounded-[24px] p-[18px] min-h-[260px]">
                  <StreamCharts streams={detailStreams} laps={detailLaps} sport={sel.sport} zones={mergedHrZoneDefs} measurementUnits={measurementUnits} />
                </section>
              {:else}
                <p class="m-0 text-[13px] text-text2 px-1">No stream data stored for this workout.{#if showRepullDataButton} Use “Repull data” on the Data tab to fetch it.{/if}</p>
              {/if}
            {/if}

            {#if detailTab === 'laps'}
              {#if detailLoading}
                <div class="rounded-[24px] bg-bg2 animate-pulse" style="height: 160px;"></div>
              {:else if detailLaps.length >= 2 || showSplitsTable}
                {#if detailLaps.length >= 2}
                  <section aria-label="Laps" class="bg-bg2 border border-border rounded-[24px] p-[18px]">
                    <LapStrip laps={detailLaps} sport={sel.sport} zones={mergedHrZoneDefs} measurementUnits={measurementUnits} />
                  </section>
                {/if}
                {#if showSplitsTable}
                {@const usePace = sel.sport === 'row' || sel.sport === 'run'}
                {@const showWatts = detailSplits.splits.some((r) => Number(r.average_watts) > 0)}
                  <section aria-label="Splits" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-3">
                    <h2 class="m-0 font-display font-normal text-[22px]">Splits</h2>
                    <div class="w-full overflow-x-auto">
                      <table class="w-full border-collapse text-[13px]">
                        <thead>
                          <tr class="text-right font-mono text-[10px] tracking-[0.06em] text-text2">
                            <th scope="col" class="py-1.5 text-left font-normal">LAP</th>
                            <th scope="col" class="font-normal">TIME</th>
                            <th scope="col" class="font-normal">DIST</th>
                            <th scope="col" class="font-normal">{usePace ? 'PACE' : 'SPEED'}</th>
                            <th scope="col" class="font-normal">HR</th>
                            {#if showWatts}<th scope="col" class="font-normal">WATTS</th>{/if}
                          </tr>
                        </thead>
                        <tbody>
                          {#each detailSplits.splits as r (r.split_number)}
                            <tr class="border-t border-border text-right font-mono text-xs tabular-nums">
                              <th scope="row" class="py-[9px] text-left font-sans font-medium">{r.split_number}</th>
                              <td>{splitTime(r.elapsed_time)}</td>
                              <td>{splitDistance(r.distance)}</td>
                              <td>{usePace ? splitPace(r.pace_seconds) : splitSpeed(r)}</td>
                              <td class="text-text1">{r.average_heartrate ? Math.round(r.average_heartrate) : '—'}</td>
                              {#if showWatts}<td>{Number(r.average_watts) > 0 ? Math.round(Number(r.average_watts)) : '—'}</td>{/if}
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>
                  </section>
                {/if}
              {:else}
                <p class="m-0 text-[13px] text-text2 px-1">No laps or splits recorded for this workout.</p>
              {/if}
            {/if}

            {#if detailTab === 'data'}
              <section aria-label="Data sources" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-4">
                <DataSources workout={selectedWorkout} />
                {#if hasActivityDetailSource(sel)}
                  {#if sel.strava_activity_id && sel.strava_streams_fetched === false && !detailHydrating && !detailStreams}
                    <p class="m-0 text-[13px] text-text2 leading-relaxed">Strava is linked, but stream data has not been imported for this workout yet. Reconnect Strava or run the Strava backfill script to load charts and GPS.</p>
                  {/if}
                  {#if showRepullDataButton}
                    <button
                      type="button"
                      class="self-start h-11 px-4 rounded-[14px] border border-border bg-transparent text-text0 text-sm font-medium cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      disabled={detailRepulling || detailLoading}
                      onclick={() => repullWorkoutData()}
                    >{detailRepulling ? 'Pulling data…' : 'Repull data'}</button>
                  {/if}
                {/if}
              </section>
            {/if}
          </div>
        </div>
      {:else}
        <div class="flex flex-col gap-3.5">
          <!-- This week -->
          <section aria-label="This week" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3.5">
            <WeekNavigator bind:value={weekPickerValue} max={format(new Date(), 'yyyy-MM-dd')} />
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
