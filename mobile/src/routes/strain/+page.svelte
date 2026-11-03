<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const strainAnalysisMemo = new SvelteMap<string, string | null>();
  const workoutAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { addDays, format, subDays } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import { CHART_ATL_STROKE, CHART_CTL_STROKE, formCssColor } from '$lib/scoreColors';
  import { canonicalHrZoneShortName, formatHrZoneTitle } from '$lib/hrZoneDisplay';
  import { normalizeUnits, workoutDistanceParts } from '$lib/utils/units';

  const CTL_IDENTITY_HEX = CHART_CTL_STROKE;
  const ATL_IDENTITY_HEX = CHART_ATL_STROKE;

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));

  const measurementUnits = $derived(
    normalizeUnits((athleteStore.profile as { measurement_units?: string })?.measurement_units)
  );

  const selectedWorkoutDistance = $derived.by(() => {
    const w = selectedWorkout;
    if (!w?.distance_m) return null;
    return workoutDistanceParts(w.distance_m, measurementUnits, w.sport);
  });

  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state('');
  let dayIndex = $state(6); // most recent on the right
  const isoDate = (value: unknown) => (typeof value === 'string' ? value.slice(0, 10) : '');

  const today = $derived(new Date());
  const todayStr = $derived(format(today, 'yyyy-MM-dd'));

  $effect(() => {
    if (!endPickerValue) {
      endPickerValue = todayStr;
      dayIndex = 6;
    }
  });

  const clampedEndDay = $derived.by(() => {
    const d = endPickerValue ? new Date(endPickerValue + 'T00:00:00') : new Date();
    if (Number.isNaN(d.getTime())) return today;
    return d > today ? today : d;
  });

  const windowStart = $derived(subDays(clampedEndDay, 6));
  const windowEnd = $derived(clampedEndDay);
  const rangeLabel = $derived(`${format(windowStart, 'MMM d')} – ${format(windowEnd, 'MMM d, yyyy')}`);
  const canGoForward = $derived(format(windowEnd, 'yyyy-MM-dd') !== todayStr);

  $effect(() => {
    pageHeader.prev = () => { endPickerValue = format(subDays(windowEnd, 1), 'yyyy-MM-dd'); dayIndex = 6; };
    pageHeader.next = () => { if (canGoForward) { endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd'); dayIndex = 6; } };
    pageHeader.canNext = canGoForward;
    pageHeader.today = () => { endPickerValue = todayStr; dayIndex = 6; };
    pageHeader.dateMax = todayStr;
    pageHeader.dateLabel = canGoForward ? format(clampedEndDay, 'EEE d MMM') : 'Today';
    pageHeader.dateMarks = Array.from(new Set([...(athleteStore.workouts ?? []).map((w: any) => String(w?.started_at ?? '').slice(0, 10)), ...(athleteStore.biometrics?.series ?? []).filter((r: any) => Number(r?.strain_score) > 0).map((r: any) => r.date)].filter(Boolean)));
    pageHeader.dateValue = format(clampedEndDay, "yyyy-MM-dd");
    return resetPageHeader;
  });

  // The header calendar writes pageHeader.dateValue; follow it.
  $effect(() => {
    const picked = pageHeader.dateValue;
    if (picked && picked !== endPickerValue && picked <= todayStr) { endPickerValue = picked; dayIndex = 6; }
  });

  const days = $derived.by(() => {
    // Build oldest→newest for display (today on the right).
    const asc = Array.from({ length: 7 }, (_, i) => {
      const d = addDays(windowStart, i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      const history = athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === dateStr);
      const dow = format(d, 'EE');
      const dayLabel = dow === 'Thu' ? 'Th' : dow.charAt(0);
      const bioStrain = Number(b?.strain_score);
      const hasBioStrain = Number.isFinite(bioStrain) && bioStrain > 0;

      // Workout-derived strain when biometrics strain is missing or stale (0 before zones synced).
      const workoutsForDay = athleteStore.workouts?.filter((w: any) => isoDate(w?.started_at) === dateStr) || [];
      const hasWorkout = workoutsForDay.length > 0;
      const workoutStrainScore = Math.min(
        100,
        Math.round(
          workoutsForDay.reduce((acc: number, w: any) => {
            const s = Number(w?.strain_score);
            if (!Number.isNaN(s) && s > 0) return acc + s;
            const tss = Number(w?.tss);
            if (!Number.isNaN(tss) && tss > 0) return acc + (tss / 150) * 100;
            return acc;
          }, 0),
        ),
      );
      const computedScore =
        hasWorkout || !hasBioStrain
          ? Math.max(hasBioStrain ? Math.round(bioStrain) : 0, workoutStrainScore)
          : Math.round(bioStrain);

      return {
        date: dateStr,
        label: dateStr === todayStr ? 'Today' : format(d, 'MMM d'),
        day: dayLabel,
        score: computedScore,
        ctl: history?.ctl || athleteStore.ctl || 0,
        atl: history?.atl || athleteStore.atl || 0,
        tsb: history?.tsb || athleteStore.tsb || 0,
        workouts: workoutsForDay,
        // Only show "no strain data" when a workout exists but we still can't compute strain.
        missing: hasWorkout && computedScore === 0,
        data: b
      };
    });
    return asc;
  });

  $effect(() => {
    dayIndex = Math.max(0, Math.min(6, dayIndex ?? 0));
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.atl > 0);
  
  const score = $derived(d.score || 0);
  // Strain is INVERTED relative to the other 0-100 scores: low strain is a
  // recovery day (teal), high strain is overreaching territory (red). The
  // unified bounded-score helper gets the same rule of thirds, just flipped.
  const scoreColor = $derived(boundedScoreCssColor(score, true));
  const quality = $derived(score >= 67 ? 'High' : score >= 34 ? 'Moderate' : 'Light');

  const avg7d = $derived.by(() => {
    const vals = days.map((x) => Number(x.score)).filter((v) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
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

  function getDurationSecs(w: any): number {
    const direct = w?.duration_secs ?? w?.duration_seconds;
    if (Number.isFinite(direct)) return Math.max(0, Math.floor(Number(direct)));
    return 0;
  }

  type ZoneBreakdown = {
    validSeconds: number;
    zoneSeconds: number[]; // index 0..4 ⇒ Z1..Z5
    zonePct: number[]; // index 0..4 ⇒ Z1..Z5
  };

  function computeZoneBreakdown(workouts: any[]): ZoneBreakdown {
    const zoneSeconds = [0, 0, 0, 0, 0];
    let validSeconds = 0;

    for (let i = 0; i < workouts.length; i++) {
      const w = workouts[i];
      // We treat zone data as present if at least Z1 exists (matches other pages' convention).
      if (w?.hr_zone_1_pct === null || w?.hr_zone_1_pct === undefined) continue;

      const duration = getDurationSecs(w);
      if (!duration) continue;

      const z1 = Number(w?.hr_zone_1_pct || 0);
      const z2 = Number(w?.hr_zone_2_pct || 0);
      const z3 = Number(w?.hr_zone_3_pct || 0);
      const z4 = Number(w?.hr_zone_4_pct || 0);
      const z5 = Number(w?.hr_zone_5_pct || 0);

      const pcts = [z1, z2, z3, z4, z5];
      for (let zi = 0; zi < 5; zi++) zoneSeconds[zi] += (duration * pcts[zi]) / 100;
      validSeconds += duration;
    }

    if (!validSeconds) return { validSeconds: 0, zoneSeconds, zonePct: [0, 0, 0, 0, 0] };

    // Round to whole % and normalize so it sums to exactly 100.
    let zonePct = zoneSeconds.map((s) => Math.round((s / validSeconds) * 100));
    let sum = zonePct.reduce((a, b) => a + b, 0);
    if (sum !== 100 && sum > 0) {
      const maxIdx = zonePct.indexOf(Math.max(...zonePct));
      zonePct[maxIdx] += 100 - sum;
    }

    return { validSeconds, zoneSeconds, zonePct };
  }

  let selectedWorkout = $state<any>(null);
  let showWorkoutModal = $state(false);

  function openWorkoutDetails(w: any) {
    selectedWorkout = w;
    showWorkoutModal = true;
  }

  function viewSelectedWorkout() {
    const workoutId = selectedWorkout?.id;
    if (!workoutId) return;

    showWorkoutModal = false;
    const target = resolve(`/training?workout_id=${encodeURIComponent(String(workoutId))}`);
    goto(target, { keepFocus: true, noScroll: true });
  }

  let workoutAnalysisLoading = $state(false);
  async function loadWorkoutAnalysis(workoutId: string) {
    if (authStore.tier !== 'premium') return;
    if (workoutAnalysisMemo.has(workoutId)) return;
    workoutAnalysisLoading = true;
    try {
      const res = await api.get(`/v1/analysis/workout/${workoutId}`);
      workoutAnalysisMemo.set(workoutId, res?.analysis?.content ?? null);
    } finally {
      workoutAnalysisLoading = false;
    }
  }

  $effect(() => {
    const workoutId = selectedWorkout?.id;
    if (!showWorkoutModal || !workoutId) {
      return;
    }
    void loadWorkoutAnalysis(workoutId);
  });

  const dayZones = $derived.by(() => computeZoneBreakdown(d?.workouts || []));

  const formatMinutes = (secs: number) => {
    const m = Math.round(Math.max(0, secs) / 60);
    return m < 1 ? '0m' : `${m}m`;
  };

  let analysisText = $state<string | null>(null);
  let analysisLoading = $state(false);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    const scopeKey = d?.date;
    if (!scopeKey) {
      analysisText = null;
      return;
    }

    const cached = strainAnalysisMemo.get(scopeKey);
    if (cached !== undefined) {
      analysisText = cached;
      return;
    }

    analysisText = null;

    const requestKey = `strain-analysis:${scopeKey}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        analysisLoading = true;
        const res = await api.get<{ analysis: { content: string } }>(`/v1/analysis/strain?day=${scopeKey}`);
        const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
        if (activeAnalysisKey !== requestKey) return;
        const next = content || null;
        strainAnalysisMemo.set(scopeKey, next);
        analysisText = next;
      } catch {
        if (activeAnalysisKey !== requestKey) return;
        strainAnalysisMemo.set(scopeKey, null);
      } finally {
        if (activeAnalysisKey === requestKey) analysisLoading = false;
      }
    })();
  });
</script>

<div class="flex flex-col gap-3.5">
  {#if !isConnected}
    <EmptyState title="No Strain Data" message="Connect WHOOP, Garmin, or Apple Health to track your daily strain." />
  {:else if !hasData}
    <EmptyState title="Waiting for Data" message="We're waiting for your first activity to compute strain." icon="⏳" />
  {:else}
    <!-- Score -->
    <section aria-label="Strain score" class="bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex gap-[18px] items-center">
      <div class="relative w-[112px] h-[112px] shrink-0">
        <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true" class="block -rotate-90">
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--border)" stroke-width="8"></circle>
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--blue)" stroke-width="8" stroke-linecap="round" stroke-dasharray="{(Math.min(score, 100) / 100) * 301.6} 302"></circle>
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <span class="font-display text-[42px] leading-none">{Math.round(score)}</span>
          <span class="font-mono text-[10px] text-text2">/ 100</span>
        </div>
      </div>
      <div class="flex flex-col gap-1.5">
        <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{quality}</span>
        <p class="m-0 text-sm leading-[1.45] text-text1">
          {score >= 67 ? 'High load today. Prioritise sleep and easy movement next.'
            : score >= 34 ? 'Moderate load. Anything more is extra fatigue going into your next session.'
            : 'Light load so far. There is room to add quality work if the plan calls for it.'}
        </p>
      </div>
    </section>

    <!-- Fitness / Fatigue / Form -->
    <dl class="m-0 grid grid-cols-3 gap-2">
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fitness</dt><dd class="m-0 text-[19px] font-medium">{d.ctl ? d.ctl.toFixed(1) : '--'}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fatigue</dt><dd class="m-0 text-[19px] font-medium">{d.atl ? d.atl.toFixed(1) : '--'}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Form</dt><dd class="m-0 text-[19px] font-medium" style="color: {formCssColor(d.tsb)}">{d.tsb > 0 ? '+' : ''}{d.tsb ? d.tsb.toFixed(1) : '--'}</dd></div>
    </dl>

    <!-- Contributing activities -->
    {#if d.workouts && d.workouts.length > 0}
      <section aria-label="Contributing activities" class="flex flex-col gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">CONTRIBUTING</span>
        {#each d.workouts as w (w.id || w.started_at)}
          {@const strainVal = Number.isFinite(Number(w?.strain_score)) ? Math.round(Number(w.strain_score)) : null}
          {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
          {@const zp = [1, 2, 3, 4, 5].map((z) => Number(w?.[`hr_zone_${z}_pct`]) || 0)}
          <button type="button" class="flex flex-col gap-2.5 px-4 py-3.5 rounded-[18px] bg-bg1 border border-border text-left w-full cursor-pointer" onclick={() => openWorkoutDetails(w)}>
            <span class="flex justify-between items-baseline">
              <span class="text-sm font-medium text-text0">{w.title || (getWorkoutLabel(w.sport) + ' Session')}</span>
              <span class="font-mono text-xs text-blue">{strainVal === null ? '--' : `+${strainVal}`}</span>
            </span>
            {#if zp.some((p) => p > 0)}
              <span aria-hidden="true" class="flex gap-[3px] h-1.5">
                {#each zp as p, i (i)}
                  {#if p > 0}<span class="rounded-[3px]" style="flex: {p} 1 0; background: var(--zone-{i + 1})"></span>{/if}
                {/each}
              </span>
            {/if}
            <span class="text-xs text-text2">
              {formatMinutes(getDurationSecs(w))}{#if w.avg_hr} · {w.avg_hr} bpm avg{/if}{#if tssVal !== null} · {tssVal} TSS{/if}
            </span>
          </button>
        {/each}
      </section>
    {:else}
      <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-border">
        <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">REST</span>
        <span class="text-[13px] leading-[1.45] text-text1">No activities logged for {d.label}.</span>
      </div>
    {/if}
  {/if}
</div>

<Modal
  show={showWorkoutModal}
  title={selectedWorkout?.title || (getWorkoutLabel(selectedWorkout?.sport) + ' Details')}
  onClose={() => (showWorkoutModal = false)}
>
  {#if selectedWorkout}
    {@const selectedStrainVal = Number.isFinite(Number(selectedWorkout?.strain_score)) ? Math.round(Number(selectedWorkout.strain_score)) : null}
    {@const selectedTssVal = Number.isFinite(Number(selectedWorkout?.tss)) ? Math.round(Number(selectedWorkout.tss)) : null}
    <div class="flex flex-col gap-6">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-2xl flex items-center justify-center text-[28px] {getWorkoutBg(selectedWorkout.sport)}">
          {getWorkoutIcon(selectedWorkout.sport)}
        </div>
        <div>
          <h3 class="text-lg font-bold text-text0">{selectedWorkout.title || (getWorkoutLabel(selectedWorkout.sport) + ' Session')}</h3>
          <p class="text-xs text-text2 font-mono uppercase">
            {format(new Date(selectedWorkout.started_at), 'MMMM d, yyyy')} · {format(new Date(selectedWorkout.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'HH:mm' : 'h:mm a')}
          </p>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Intensity</p>
          <div class="flex items-baseline gap-1">
            <span class="text-[20px] font-bold tabular-nums" style:color={boundedScoreCssColor(selectedStrainVal)}>
              {selectedStrainVal === null ? '--' : selectedStrainVal}
            </span>
            <span class="text-[10px] text-text2 font-mono">STRAIN</span>
          </div>
        </div>
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Duration</p>
          <div class="flex items-baseline gap-1">
            <span class="text-[20px] font-bold text-text0">{Math.floor(getDurationSecs(selectedWorkout) / 60)}</span>
            <span class="text-[10px] text-text2 font-mono">MIN</span>
          </div>
        </div>
        {#if selectedWorkout.avg_hr}
          <div class="p-4 rounded-2xl bg-glass border border-border/50">
            <p class="text-[10px] text-text2 font-mono uppercase mb-1">Avg HR</p>
            <div class="flex items-baseline gap-1">
              <span class="text-[20px] font-bold text-text0">{selectedWorkout.avg_hr}</span>
              <span class="text-[10px] text-text2 font-mono">BPM</span>
            </div>
          </div>
        {/if}
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Stress</p>
          <div class="flex items-baseline gap-1">
            <span
              class="text-[20px] font-bold tabular-nums"
              style:color={boundedScoreCssColor(selectedTssVal === null ? null : selectedStrainVal, true)}
            >
              {selectedTssVal === null ? '--' : selectedTssVal}
            </span>
            <span class="text-[10px] text-text2 font-mono">TSS</span>
          </div>
        </div>
        {#if selectedWorkoutDistance}
          <div class="p-4 rounded-2xl bg-glass border border-border/50">
            <p class="text-[10px] text-text2 font-mono uppercase mb-1">Distance</p>
            <div class="flex items-baseline gap-1">
              <span class="text-[20px] font-bold text-text0">{selectedWorkoutDistance.value}</span>
              <span class="text-[10px] text-text2 font-mono uppercase">{selectedWorkoutDistance.unit}</span>
            </div>
          </div>
        {/if}
      </div>

      <button
        type="button"
        class="w-full rounded-xl border border-blue/30 bg-blue/10 px-4 py-3 text-[13px] font-semibold text-blue transition-colors hover:bg-blue/15 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!selectedWorkout.id}
        onclick={viewSelectedWorkout}
      >
        View full workout
      </button>

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
      {/if}

      {#if selectedWorkout.hr_zone_1_pct !== undefined || selectedWorkout.hr_zone_2_pct !== undefined}
        <div class="flex flex-col gap-4">
          <p class="text-[13px] font-semibold">Heart Rate Zones</p>
          <div class="flex flex-col gap-3">
            {#each [5, 4, 3, 2, 1] as zone (zone)}
              {@const pct = selectedWorkout[`hr_zone_${zone}_pct`] || 0}
              {@const zTitle = formatHrZoneTitle(zone)}
              <div class="flex items-center gap-3">
                <div class="min-w-[5.25rem] max-w-[6rem] flex items-center gap-1.5 shrink-0">
                  <div class="w-2 h-2 shrink-0 rounded-full" style="background: var(--zone-{zone})"></div>
                  <div class="min-w-0 leading-tight" title={zTitle}>
                    <span class="block text-[10px] font-mono text-text2">Z{zone}</span>
                    <span class="block text-[9px] text-text2 truncate">{canonicalHrZoneShortName(zone)}</span>
                  </div>
                </div>
                <div class="flex-1 h-1.5 bg-glass rounded-full overflow-hidden relative">
                   <div 
                    class="absolute inset-y-0 left-0 rounded-full transition-all duration-500" 
                    style="width: {pct}%; background: var(--zone-{zone})"
                  ></div>
                </div>
                <div class="w-8 text-right shrink-0">
                  <span class="text-[11px] font-bold font-mono {pct > 0 ? 'text-text1' : 'text-text2'}">{pct}%</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <div class="p-4 rounded-xl bg-glass border border-border/50 flex flex-col gap-2">
         <div class="flex justify-between items-center">
            <span class="text-xs text-text2">Source</span>
            <span class="text-xs font-mono font-medium text-text1 uppercase">{selectedWorkout.source || 'Manual'}</span>
         </div>
         {#if selectedWorkout.norm_power_w}
          <div class="flex justify-between items-center">
              <span class="text-xs text-text2">Normalized Power</span>
              <span class="text-xs font-mono font-medium text-text1">{selectedWorkout.norm_power_w} W</span>
          </div>
         {/if}
      </div>
    </div>
  {/if}
</Modal>
