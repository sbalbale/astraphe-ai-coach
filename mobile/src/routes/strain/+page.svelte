<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const workoutAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import { localDay } from '$lib/utils/localDay';
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import DashedNote from '$lib/components/ui/DashedNote.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { bodyDate, rememberBodyDate } from '$lib/stores/bodyDate.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { hasPremiumAccess } from '$lib/utils/tier';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { addDays, format, subDays } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import { CHART_ATL_STROKE, CHART_CTL_STROKE, formCssColor } from '$lib/scoreColors';
  import { canonicalHrZoneShortName } from '$lib/hrZoneDisplay';
  import { normalizeUnits, workoutDistanceParts } from '$lib/utils/units';
  import { workoutDurationSecs } from '$lib/utils/workoutDuration';
  import { viewport } from '$lib/stores/viewport.svelte';
  import { bodyEyebrow, dayStrain, workoutStrainContribution } from '$lib/utils/bodyWide';
  import BodyScoreTabs from '$lib/components/wide/body/BodyScoreTabs.svelte';
  import StrainWide from '$lib/components/wide/body/StrainWide.svelte';

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
  let endPickerValue = $state(bodyDate.value ?? '');
  let dayIndex = $state(6); // most recent on the right
  const isoDate = (value: unknown) => (typeof value === 'string' ? value.slice(0, 10) : '');
  /** A real number (0 included) from the day's row, else the fallback, else null. */
  const loadValue = (v: unknown, fallback: unknown): number | null => {
    for (const x of [v, fallback]) if (x != null && Number.isFinite(Number(x))) return Number(x);
    return null;
  };

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
  /** The day picked in the 7-day strip; the header shows it. */
  const selectedDayStr = $derived(format(addDays(windowStart, dayIndex), 'yyyy-MM-dd'));

  $effect(() => {
    // Prev / next step the picked day; past either end of the 7-day strip, the strip moves.
    pageHeader.prev = () => { if (dayIndex > 0) dayIndex -= 1; else { endPickerValue = format(subDays(windowStart, 1), 'yyyy-MM-dd'); dayIndex = 6; } };
    pageHeader.next = () => { if (dayIndex < 6) dayIndex += 1; else if (canGoForward) { endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd'); dayIndex = 6; } };
    pageHeader.canNext = selectedDayStr !== todayStr;
    pageHeader.today = () => { endPickerValue = todayStr; dayIndex = 6; };
    pageHeader.dateMax = todayStr;
    pageHeader.dateLabel = selectedDayStr === todayStr ? 'Today' : format(addDays(windowStart, dayIndex), 'EEE d MMM');
    pageHeader.dateMarks = Array.from(new Set([...(athleteStore.workouts ?? []).map((w: any) => localDay(w?.started_at)), ...(athleteStore.biometrics?.series ?? []).filter((r: any) => Number(r?.strain_score) > 0).map((r: any) => r.date)].filter(Boolean)));
    pageHeader.dateValue = selectedDayStr;
    // Wide layouts show Recovery, Sleep and Strain as one "Body" screen.
    pageHeader.wideTitle = 'Body';
    pageHeader.wideEyebrow = bodyEyebrow(days[dayIndex]?.date ?? todayStr, days[dayIndex]?.data);
    return resetPageHeader;
  });

  // Share the picked day with the other Body sub-tabs (Recovery / Sleep / Strain).
  $effect(() => {
    rememberBodyDate(format(addDays(windowStart, dayIndex), 'yyyy-MM-dd'), todayStr);
  });

  // The header calendar writes pageHeader.dateValue; follow it.
  $effect(() => {
    // Runs only when the calendar writes (not when a day in the strip is picked).
    const picked = pageHeader.dateValue;
    if (picked && picked !== untrack(() => selectedDayStr) && picked <= todayStr) { endPickerValue = picked; dayIndex = 6; }
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
      const workoutsForDay = athleteStore.workouts?.filter((w: any) => localDay(w?.started_at) === dateStr) || [];
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
        // That day's values only; today's are a fallback for today alone (past days
        // used to show today's fitness/fatigue/form whenever their row was missing).
        ctl: loadValue(history?.ctl, dateStr === todayStr ? athleteStore.ctl : null),
        atl: loadValue(history?.atl, dateStr === todayStr ? athleteStore.atl : null),
        tsb: loadValue(history?.tsb, dateStr === todayStr ? athleteStore.tsb : null),
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
  // Any workout ever (not just this week), stored strain, or training load. The old
  // check (days.some(!missing)) was always true, so empty accounts saw a 0 score.
  const hasData = $derived(
    (athleteStore.workouts?.length ?? 0) > 0 ||
      days.some((day) => day.score > 0 || day.workouts.length > 0) ||
      athleteStore.atl > 0
  );
  // "Connect an app" only when we *know* nothing is connected and there's no data:
  // manual-only athletes (logged sleep/workouts) see their data, and connected users
  // don't flash this while the sync status is still loading.
  const showConnectPrompt = $derived(athleteStore.syncStatus != null && !isConnected && !hasData);
  
  const score = $derived(d.score || 0);

  let checking = $state(false);
  async function checkSync() {
    checking = true;
    try {
      await athleteStore.fetchAll(true);
    } finally {
      checking = false;
    }
  }
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

  function getDurationSecs(w: any): number {
    return workoutDurationSecs(w) ?? 0;
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
    if (!hasPremiumAccess(authStore.tier)) return;
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
  /** Wide layout: the day's strain split into workouts and all-day activity. */
  const wideStrain = $derived(dayStrain(d?.data, d?.workouts ?? []));

  const formatMinutes = (secs: number) => {
    const m = Math.round(Math.max(0, secs) / 60);
    return m < 1 ? '0m' : `${m}m`;
  };

  // (An AI analysis used to be requested here on every change and never shown,
  // costing an LLM generation per view. Removed.)
</script>

{#if viewport.wide && !showConnectPrompt && hasData}
  <div class="flex-1 flex flex-col gap-[22px]">
    <BodyScoreTabs active="strain" day={d.date} />
    <StrainWide
      day={d.date}
      strain={wideStrain}
      ctl={d.ctl}
      atl={d.atl}
      tsb={d.tsb}
      {days}
      selected={dayIndex}
      onSelect={(i) => (dayIndex = i)}
    />
  </div>
{:else}
<div class="flex flex-col gap-3.5">
  {#if showConnectPrompt}
    <EmptyStateCard
      icon="pulse"
      tone="blue"
      eyebrow="Not set up"
      title="Track your strain"
      message="Strain is how hard your day was, built from your workouts' heart-rate zones. Connect Garmin or WHOOP, or log sessions by hand."
      actionLabel="Connect an app"
      onAction={() => goto('/profile/connections')}
      secondaryLabel="Log an activity"
      onSecondary={() => goto('/training?log=1')}
    />
    <DashedNote label="Good to know" layout="inline">
      Hand-logged sessions count too: without heart rate, strain comes from their duration and training load.
    </DashedNote>
  {:else if !hasData}
    <EmptyStateCard
      icon="pulse"
      tone="amber"
      eyebrow="Waiting for sync"
      title="No strain yet"
      message="Your apps are connected. Strain appears after your first workout syncs, usually within a few minutes of finishing."
      actionLabel={checking ? 'Checking…' : 'Check sync now'}
      onAction={checkSync}
      secondaryLabel="Log an activity"
      onSecondary={() => goto('/training?log=1')}
    />
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
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fitness</dt><dd class="m-0 text-[19px] font-medium">{d.ctl != null ? d.ctl.toFixed(1) : '--'}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fatigue</dt><dd class="m-0 text-[19px] font-medium">{d.atl != null ? d.atl.toFixed(1) : '--'}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Form</dt><dd class="m-0 text-[19px] font-medium" style="color: {d.tsb != null ? formCssColor(d.tsb) : 'var(--text2)'}">{d.tsb != null && d.tsb > 0 ? '+' : ''}{d.tsb != null ? d.tsb.toFixed(1) : '--'}</dd></div>
    </dl>

    <!-- Contributing activities -->
    {#if d.workouts && d.workouts.length > 0}
      <section aria-label="Contributing activities" class="flex flex-col gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">CONTRIBUTING</span>
        {#each d.workouts as w (w.id || w.started_at)}
          {@const strainVal = Math.round(workoutStrainContribution(w))}
          {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
          {@const zp = [1, 2, 3, 4, 5].map((z) => Number(w?.[`hr_zone_${z}_pct`]) || 0)}
          <button type="button" class="flex flex-col gap-2.5 px-4 py-3.5 rounded-[18px] bg-bg1 border border-border text-left w-full cursor-pointer" onclick={() => openWorkoutDetails(w)}>
            <span class="flex justify-between items-baseline">
              <span class="text-sm font-medium text-text0">{w.title || (getWorkoutLabel(w.sport) + ' Session')}</span>
              <span class="font-mono text-xs text-blue">+{strainVal}</span>
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
{/if}

<Modal
  show={showWorkoutModal}
  title={selectedWorkout ? `${getWorkoutLabel(selectedWorkout.sport)} · ${format(new Date(selectedWorkout.started_at), 'EEE d MMM')}` : 'Workout'}
  onClose={() => (showWorkoutModal = false)}
>
  {#if selectedWorkout}
    {@const w = selectedWorkout}
    {@const strainVal = Math.round(workoutStrainContribution(w))}
    {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
    {@const secs = getDurationSecs(w)}
    {@const zp = [1, 2, 3, 4, 5].map((z) => Number(w?.[`hr_zone_${z}_pct`]) || 0)}
    {@const tiles = [
      { k: 'Strain', v: `+${strainVal}`, c: 'text-blue' },
      { k: 'Duration', v: secs >= 3600 ? `${Math.floor(secs / 3600)}h ${String(Math.round((secs % 3600) / 60)).padStart(2, '0')}m` : formatMinutes(secs), c: 'text-text0' },
      tssVal !== null ? { k: 'TSS', v: String(tssVal), c: 'text-text0' } : null,
      w.avg_hr ? { k: 'Avg HR', v: `${w.avg_hr} bpm`, c: 'text-text0' } : null,
      selectedWorkoutDistance ? { k: 'Distance', v: `${selectedWorkoutDistance.value} ${selectedWorkoutDistance.unit.toLowerCase()}`, c: 'text-text0' } : null,
      w.norm_power_w ? { k: 'Norm. power', v: `${w.norm_power_w} W`, c: 'text-text0' } : null
    ].filter((t) => t !== null)}
    <div class="flex flex-col gap-4">
      <div class="flex flex-col gap-1">
        <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">
          {getWorkoutLabel(w.sport)} · {format(new Date(w.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'HH:mm' : 'h:mm a')}
        </span>
        <h3 class="m-0 font-display font-normal text-[32px] leading-[1.05] text-text0">{w.title || `${getWorkoutLabel(w.sport)} session`}</h3>
      </div>

      <div class="grid grid-cols-2 gap-2">
        {#each tiles as t (t.k)}
          <div class="px-3.5 py-3 rounded-2xl bg-bg2 border border-border flex flex-col gap-0.5">
            <span class="text-[20px] font-medium tabular-nums {t.c}">{t.v}</span>
            <span class="text-[12px] text-text2">{t.k}</span>
          </div>
        {/each}
      </div>

      {#if zp.some((p) => p > 0)}
        <section aria-label="Heart-rate zones" class="flex flex-col gap-2.5 p-4 rounded-[20px] bg-bg2 border border-border">
          <span class="font-display text-[20px] leading-none">Heart-rate zones</span>
          <span aria-hidden="true" class="flex gap-[3px] h-1.5">
            {#each zp as p, i (i)}
              {#if p > 0}<span class="rounded-[3px]" style="flex: {p} 1 0; background: var(--zone-{i + 1})"></span>{/if}
            {/each}
          </span>
          {#each [5, 4, 3, 2, 1] as zone (zone)}
            {@const p = zp[zone - 1]}
            <div class="flex items-center gap-2.5 text-[13px] {p > 0 ? 'text-text0' : 'text-text3'}">
              <span aria-hidden="true" class="w-2 h-2 rounded-sm shrink-0" style="background: var(--zone-{zone}); opacity: {p > 0 ? 1 : 0.4}"></span>
              <span class="font-mono text-[12px] w-6">Z{zone}</span>
              <span class="flex-1 truncate {p > 0 ? 'text-text1' : ''}">{canonicalHrZoneShortName(zone)}</span>
              <span class="font-mono text-[12px] w-10 text-right">{p}%</span>
              <span class="font-mono text-[12px] w-12 text-right text-text2">{formatMinutes((p / 100) * secs)}</span>
            </div>
          {/each}
        </section>
      {/if}

      {#if hasPremiumAccess(authStore.tier)}
        <section aria-label="Coach analysis" class="flex flex-col gap-2 p-4 rounded-[20px] bg-bg1 border border-dashed border-popover-border">
          <span class="font-mono text-[10px] tracking-[0.12em] text-blue">COACH ANALYSIS</span>
          {#if workoutAnalysisLoading && !workoutAnalysisMemo.has(w.id)}
            <p class="m-0 text-sm text-text2 animate-pulse">Analyzing workout…</p>
          {:else}
            <p class="m-0 text-[14px] leading-[1.55] text-text1">{workoutAnalysisMemo.get(w.id) ?? 'Insight unavailable.'}</p>
          {/if}
        </section>
      {/if}

      <button
        type="button"
        class="w-full h-12 rounded-[14px] border-0 bg-blue text-on-accent text-[15px] font-semibold cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!w.id}
        onclick={viewSelectedWorkout}
      >
        Open workout
      </button>
    </div>
  {/if}
</Modal>
