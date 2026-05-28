<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';
  const zonesAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import MonthPicker from '$lib/components/MonthPicker.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { HR_ZONE_HEX, HR_ZONE_LABELS } from '$lib/hrZoneDisplay';
  import {
    addDays,
    addMonths,
    endOfDay,
    endOfMonth,
    format,
    isWithinInterval,
    startOfDay,
    startOfMonth,
    subDays
  } from 'date-fns';

  let sport = $state('all');
  let editZone: number | null = $state(null);

  type WindowMode = 'week' | 'month';
  let windowMode: WindowMode = $state('week');

  const pad2 = (n: number) => String(n).padStart(2, '0');
  const toDateInputValue = (d: Date) =>
    `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  const toMonthInputValue = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
  const parseDateInputLocal = (value: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!m) return new Date(value);
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    // Use local time to avoid timezone shifting when parsing YYYY-MM-DD
    return new Date(y, mo - 1, d, 12, 0, 0, 0);
  };

  // Default to "today" in local time for inputs.
  let selectedDay = $state(toDateInputValue(new Date()));
  let selectedMonth = $state(toMonthInputValue(new Date()));
  let dayPickerValue = $state('');
  let monthPickerValue = $state('');

  function jumpToToday() {
    const now = new Date();
    if (windowMode === 'week') selectedDay = toDateInputValue(now);
    else selectedMonth = toMonthInputValue(now);
  }

  $effect(() => {
    dayPickerValue = selectedDay;
    monthPickerValue = selectedMonth;
  });

  $effect(() => {
    if (windowMode === 'week') selectedDay = dayPickerValue;
  });

  $effect(() => {
    if (windowMode === 'month') selectedMonth = monthPickerValue;
  });

  /** Local calendar caps for navigation and pickers (ISO strings compare lexicographically). */
  const todayDayMax = $derived(toDateInputValue(new Date()));
  const todayMonthMax = $derived(toMonthInputValue(new Date()));

  $effect(() => {
    if (selectedDay > todayDayMax) selectedDay = todayDayMax;
  });
  $effect(() => {
    if (selectedMonth > todayMonthMax) selectedMonth = todayMonthMax;
  });

  const canGoForwardWeek = $derived(
    toDateInputValue(addDays(parseDateInputLocal(selectedDay), 7)) <= todayDayMax
  );
  const canGoForwardMonth = $derived(
    toMonthInputValue(addMonths(parseDateInputLocal(`${selectedMonth}-01`), 1)) <= todayMonthMax
  );
  const canGoForward = $derived(windowMode === 'week' ? canGoForwardWeek : canGoForwardMonth);

  const METHOD_LABEL: Record<string, string> = {
    lthr: 'Coggan LTHR',
    hrr: 'Karvonen HRR',
    max_hr: 'Max HR %'
  };

  /** Descriptions by zone number — API returns exactly five HR zones for every method */
  const ZONE_DESCRIPTIONS: Record<number, string> = {
    1: 'Recovery and very easy aerobic work.',
    2: 'Steady endurance. Aerobic base and fat metabolism.',
    3: 'Moderate-hard. Tempo and sustainable hard efforts.',
    4: 'Threshold. Race-pace sustainable intensity.',
    5: 'VO2max+. Hard intervals and short maximal efforts.'
  };

  /** Time-in-zones stacked bar labels (always Z1-Z5 — no WHOOP-only Z0 bucket) */
  const TIME_IN_ZONES_LABELS = [1, 2, 3, 4, 5].map((z) => `Z${z} · ${HR_ZONE_LABELS[z]}`);

  const hasProfile = $derived(!!athleteStore.profile);

  const zoneMethod = $derived(athleteStore.profile?.hr_zones?.method ?? null);
  const zoneAnchorLabel = $derived(athleteStore.profile?.hr_zones?.anchor_label ?? '');

  const hrZones = $derived(
    (athleteStore.profile?.hr_zones?.zones ?? []).map((z: { zone: number; name: string; min: number; max: number }) => ({
      zone: z.zone,
      name: HR_ZONE_LABELS[z.zone] ?? z.name,
      lo: z.min,
      hi: z.max,
      color: HR_ZONE_HEX[z.zone] ?? '#AAB3BF',
      desc: ZONE_DESCRIPTIONS[z.zone] ?? ''
    }))
  );

  const hasZoneDefinitions = $derived(hrZones.length > 0);

  /** Scale zone bars (open-ended Z5 uses max 999 sentinel) */
  const displayCeiling = $derived.by(() => {
    const profileMax = athleteStore.profile?.max_hr;
    let cap = typeof profileMax === 'number' ? profileMax : 0;
    for (const z of hrZones) {
      if (z.hi < 500) cap = Math.max(cap, z.hi);
      if (z.lo < 500) cap = Math.max(cap, z.lo);
    }
    return cap > 0 ? cap : 1;
  });

  const maxHRKnown = $derived(
    typeof athleteStore.profile?.max_hr === 'number' ? athleteStore.profile.max_hr : null
  );
  const restingHRKnown = $derived(
    typeof athleteStore.profile?.resting_hr === 'number' ? athleteStore.profile.resting_hr : null
  );
  const hrrKnown = $derived(
    maxHRKnown != null && restingHRKnown != null ? maxHRKnown - restingHRKnown : null
  );

  /** Zone Definitions card: high intensity first (Z5 → Z1). */
  let zones = $derived([...hrZones].sort((a, b) => b.zone - a.zone));

  
  // Filter activities
  const sportOptions = [
    { id: 'all', label: '🌍 Overview' },
    { id: 'run', label: '🏃 Run' },
    { id: 'bike', label: '🚴 Bike' },
    { id: 'swim', label: '🏊 Swim' },
    { id: 'strength', label: '💪 Strength' },
    { id: 'mobility', label: '🧘 Mobility' },
    { id: 'row', label: '🚣 Row' },
    { id: 'other', label: '🏁 Other' }
  ];

  const sportAliases: Record<string, string[]> = {
    run: ['run', 'running'],
    bike: ['bike', 'cycling'],
    swim: ['swim', 'swimming'],
    row: ['row', 'rowing'],
    mobility: ['mobility', 'yoga', 'stretching', 'stretch', 'pilates']
  };

  const sportFilteredWorkouts = $derived(
    sport === 'all'
      ? athleteStore.workouts
      : athleteStore.workouts.filter((w) => {
          const s = w.sport?.toLowerCase();
          if (!s) return false;
          if (sport === 'strength') return s === 'strength' || s === 'strength_training' || s === 'gym';
          const aliases = sportAliases[sport];
          if (aliases) return aliases.includes(s);
          return s === sport;
        })
  );

  const windowStart = $derived.by(() => {
    if (windowMode === 'week') {
      // Rolling 7-day window ending on the selected day (inclusive)
      const anchor = parseDateInputLocal(selectedDay);
      return startOfDay(subDays(anchor, 6));
    }
    const monthDate = new Date(`${selectedMonth}-01T00:00:00`);
    return startOfMonth(monthDate);
  });

  const windowEnd = $derived.by(() => {
    if (windowMode === 'week') {
      const anchor = parseDateInputLocal(selectedDay);
      return endOfDay(anchor);
    }
    const monthDate = new Date(`${selectedMonth}-01T00:00:00`);
    return endOfMonth(monthDate);
  });

  const windowLabel = $derived.by(() => {
    if (windowMode === 'week') {
      return `${format(windowStart, 'MMM d')} – ${format(windowEnd, 'MMM d, yyyy')}`;
    }
    return format(windowStart, 'MMM yyyy');
  });

  const timeAndSportFilteredWorkouts = $derived.by(() => {
    const start = windowStart;
    const end = windowEnd;
    return sportFilteredWorkouts.filter((w) => {
      const raw = (w as any).started_at;
      if (!raw) return false;
      const startedAt = new Date(raw);
      if (Number.isNaN(startedAt.getTime())) return false;
      return isWithinInterval(startedAt, { start, end });
    });
  });

  const hasWorkouts = $derived(timeAndSportFilteredWorkouts.length > 0);

  let zonesAnalysisText = $state<string | null>(null);
  let zonesAnalysisLoading = $state(false);
  let activeZonesAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    void windowMode;
    void selectedDay;
    void selectedMonth;
    void sport;

    const scopeKey = `${windowMode}:${windowMode === 'week' ? selectedDay : selectedMonth}:${sport}`;
    const cached = zonesAnalysisMemo.get(scopeKey);
    if (cached !== undefined) {
      zonesAnalysisText = cached;
      return;
    }

    zonesAnalysisText = null;
    const requestKey = `zones-analysis:${scopeKey}`;
    activeZonesAnalysisKey = requestKey;

    (async () => {
      try {
        zonesAnalysisLoading = true;
        const windowStartStr = format(windowStart, 'yyyy-MM-dd');
        const windowEndStr = format(windowEnd, 'yyyy-MM-dd');
        const res = await api.get<{ analysis: { content: string } }>(
          `/v1/analysis/time-in-zones?window_start=${windowStartStr}&window_end=${windowEndStr}&sport=${sport}`
        );
        const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
        if (activeZonesAnalysisKey !== requestKey) return;
        const next = content || null;
        zonesAnalysisMemo.set(scopeKey, next);
        zonesAnalysisText = next;
      } catch {
        if (activeZonesAnalysisKey !== requestKey) return;
        zonesAnalysisMemo.set(scopeKey, null);
      } finally {
        if (activeZonesAnalysisKey === requestKey) zonesAnalysisLoading = false;
      }
    })();
  });

  // Memoize distribution calculation
  const distribution = $derived.by(() => {
    if (!hasWorkouts)
      return { pcts: [0, 0, 0, 0, 0] as number[], validCount: 0, totalCount: 0 };

    let totals = [0, 0, 0, 0, 0];
    let validCount = 0;

    // Use a single pass over workouts
    for (let i = 0; i < timeAndSportFilteredWorkouts.length; i++) {
      const w = timeAndSportFilteredWorkouts[i];
      if (w.hr_zone_1_pct !== null) {
        const z1 = Number(w.hr_zone_1_pct || 0);
        const z2 = Number(w.hr_zone_2_pct || 0);
        const z3 = Number(w.hr_zone_3_pct || 0);
        const z4 = Number(w.hr_zone_4_pct || 0);
        const z5 = Number(w.hr_zone_5_pct || 0);

        totals[0] += z1;
        totals[1] += z2;
        totals[2] += z3;
        totals[3] += z4;
        totals[4] += z5;
        validCount++;
      }
    }

    if (validCount === 0) {
      return { pcts: [0, 0, 0, 0, 0] as number[], validCount: 0, totalCount: timeAndSportFilteredWorkouts.length };
    }

    const count = validCount;

    // Normalize to sum to exactly 100%
    let rounded = totals.map((t) => Math.round(t / count));
    let sum = rounded.reduce((a, b) => a + b, 0);

    if (sum !== 100 && sum > 0) {
      // Adjust the largest zone to make it exactly 100%
      let maxIdx = rounded.indexOf(Math.max(...rounded));
      rounded[maxIdx] += 100 - sum;
    }

    return { pcts: rounded, validCount, totalCount: timeAndSportFilteredWorkouts.length };
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Heart Rate & Power</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Zones</h1>
    {#if zoneMethod && zoneAnchorLabel}
      <p class="text-text2 font-mono text-xs mt-1">
        {METHOD_LABEL[zoneMethod] ?? zoneMethod} · {zoneAnchorLabel}
      </p>
    {/if}
  </div>

  {#if athleteStore.loading && !athleteStore.initialLoadDone}
    <div class="flex-1 flex flex-col items-center justify-center py-20 opacity-40">
      <div class="w-6 h-6 border-2 border-blue border-t-transparent rounded-full animate-spin mb-4"></div>
      <p class="text-[10px] font-mono tracking-widest uppercase">Syncing Biometrics...</p>
    </div>
  {:else if !hasProfile}
    <EmptyState 
      title="No Profile Data" 
      message="Complete your athlete profile to compute personalized training zones."
      actionLabel="Go to Profile"
      icon="👤"
    />
  {:else if !hasZoneDefinitions}
    <EmptyState
      title="Incomplete HR Data"
      message="Add at least a max heart rate (or a manual lactate threshold HR) in training settings to display zones."
      actionLabel="Training settings"
      icon="📈"
    />
  {:else}
    {#if zoneMethod === 'max_hr'}
      <button
        type="button"
        class="text-left text-[11px] text-text2 font-mono"
        onclick={() => goto('/profile/training-settings')}
      >
        Add your resting heart rate to get more personalized zones →
      </button>
    {/if}

    <!-- Sport toggle -->
    <div class="flex gap-1.5 overflow-x-auto pb-2 no-scrollbar shrink-0">
      {#each sportOptions as s (s.id)}
        <Pill active={sport === s.id} onclick={() => sport = s.id}>
          {s.label}
        </Pill>
      {/each}
    </div>

    <!-- Anchor values -->
    <div class="grid grid-cols-2 gap-2.5">
      <Card class="!bg-gradient-to-br from-red/10 via-transparent to-transparent">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Max Heart Rate</p>
        <p class="text-[26px] font-bold text-red tracking-[-0.02em] leading-tight">
          {maxHRKnown ?? '—'}
          {#if maxHRKnown != null}
            <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
          {/if}
        </p>
        <p class="text-[10px] text-text2 mt-0.5">Profile Baseline</p>
      </Card>
      <Card class="!bg-gradient-to-br from-[rgba(87,155,250,0.12)] via-transparent to-transparent">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Resting Heart Rate</p>
        <p class="text-[26px] font-bold tracking-[-0.02em] leading-tight" style="color: {HR_ZONE_HEX[1]}">
          {restingHRKnown ?? '—'}
          {#if restingHRKnown != null}
            <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
          {/if}
        </p>
        <p class="text-[10px] text-text2 mt-0.5">
          {#if hrrKnown != null}
            HRR: {hrrKnown} bpm
          {:else}
            Needed for Karvonen zones
          {/if}
        </p>
      </Card>
    </div>

    <!-- Zone Bars -->
    <Card>
      <p class="text-[13px] font-semibold mb-3.5">Zone Definitions</p>
      <div class="flex flex-col gap-2.5">
        {#each zones as z, i (z.zone)}
          {@const barHi = z.hi >= 500 ? displayCeiling : z.hi}
          {@const barLo = Math.min(z.lo, barHi)}
          <button 
            class="flex flex-col text-left bg-transparent border-none p-0 cursor-pointer w-full text-text0"
            onclick={() => editZone = editZone === i ? null : i}
          >
            <div class="flex items-center gap-2.5 mb-1.5 w-full">
              <div class="w-7 h-7 rounded-lg border flex items-center justify-center shrink-0" 
                   style="background: {z.color}20; border-color: {z.color}50;">
                <span class="text-[11px] font-bold font-mono" style="color: {z.color}">Z{z.zone}</span>
              </div>
              <div class="flex-1">
                <div class="flex justify-between items-center mb-1">
                  <span class="text-[12px] font-semibold">{z.name}</span>
                  <span class="text-[11px] font-mono" style="color: {z.color}">
                    {z.hi >= 500 ? `${z.lo}+` : `${z.lo}–${z.hi}`} bpm
                  </span>
                </div>
                <div class="h-1.25 bg-glass2 rounded overflow-hidden">
                  <div class="h-full rounded" 
                       style="width: {(displayCeiling > 0 ? (barHi - barLo) / displayCeiling : 0) * 100}%; margin-left: {(displayCeiling > 0 ? barLo / displayCeiling : 0) * 100}%; background: {z.color};"></div>
                </div>
              </div>
            </div>
            {#if editZone === i}
              <div class="ml-[38px] p-2 px-2.5 bg-glass rounded-lg border-l-2 mt-1 w-[calc(100%-38px)]" style="border-color: {z.color}">
                <p class="text-[11px] text-text1 leading-relaxed mb-2">{z.desc}</p>
              </div>
            {/if}
          </button>
        {/each}
      </div>
    </Card>

    <!-- Weekly distribution -->
    <Card>
      <p class="text-[13px] font-semibold mb-3">Time in Zones ({sport === 'all' ? 'All Activities' : sport.toUpperCase()})</p>
      <div class="flex flex-col gap-2.5 mb-3 min-w-0">
        <div class="flex flex-col gap-2 min-w-0 sm:flex-row sm:items-center sm:gap-2">
          <div class="flex bg-glass2 border border-border/50 rounded-lg overflow-hidden shrink-0 w-fit">
            <button
              class="px-2.5 py-1 text-[10px] font-mono uppercase tracking-widest transition-colors {windowMode === 'week' ? 'bg-glass text-text0' : 'text-text2 hover:text-text0'}"
              onclick={() => windowMode = 'week'}
              type="button"
            >
              Week
            </button>
            <button
              class="px-2.5 py-1 text-[10px] font-mono uppercase tracking-widest transition-colors {windowMode === 'month' ? 'bg-glass text-text0' : 'text-text2 hover:text-text0'}"
              onclick={() => windowMode = 'month'}
              type="button"
            >
              Month
            </button>
          </div>

          <div class="flex items-center gap-1.5 min-w-0 w-full sm:flex-1 sm:justify-end">
            <button
              class="w-7 h-7 shrink-0 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors flex items-center justify-center text-text1"
              onclick={() => {
                if (windowMode === 'week') selectedDay = toDateInputValue(addDays(parseDateInputLocal(selectedDay), -7));
                else selectedMonth = toMonthInputValue(addMonths(parseDateInputLocal(`${selectedMonth}-01`), -1));
              }}
              type="button"
              aria-label={windowMode === 'week' ? 'Previous 7 days' : 'Previous month'}
              title={windowMode === 'week' ? 'Previous 7 days' : 'Previous month'}
            >
              ‹
            </button>

            {#if windowMode === 'week'}
              <div class="min-w-0 flex-1 sm:flex-none sm:w-[130px]">
                <DatePicker
                  id="zones-week"
                  bind:value={dayPickerValue}
                  max={todayDayMax}
                  ariaLabel="Select end date"
                  buttonClass="h-7 px-2 pr-2 rounded-lg bg-glass2 border border-border/50 text-[10px] font-mono text-text1"
                />
              </div>
            {:else}
              <div class="min-w-0 flex-1 sm:flex-none sm:w-[130px]">
                <MonthPicker
                  id="zones-month"
                  bind:value={monthPickerValue}
                  max={todayMonthMax}
                  ariaLabel="Select month"
                  buttonClass="h-7 px-2 pr-2 rounded-lg bg-glass2 border border-border/50 text-[10px] font-mono text-text1"
                />
              </div>
            {/if}

            <button
              class="h-7 shrink-0 px-2 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors text-[10px] font-mono text-text1 whitespace-nowrap"
              onclick={jumpToToday}
              type="button"
              aria-label="Jump to current week/month"
              title="Today"
            >
              Today
            </button>

            <button
              class="w-7 h-7 shrink-0 rounded-lg bg-glass2 border border-border/50 transition-colors flex items-center justify-center text-text1 {canGoForward ? 'hover:bg-glass' : 'opacity-40 cursor-not-allowed'}"
              onclick={() => {
                if (!canGoForward) return;
                if (windowMode === 'week') selectedDay = toDateInputValue(addDays(parseDateInputLocal(selectedDay), 7));
                else selectedMonth = toMonthInputValue(addMonths(parseDateInputLocal(`${selectedMonth}-01`), 1));
              }}
              type="button"
              disabled={!canGoForward}
              aria-label={windowMode === 'week' ? 'Next 7 days' : 'Next month'}
              title={canGoForward ? (windowMode === 'week' ? 'Next 7 days' : 'Next month') : 'Cannot go past today'}
            >
              ›
            </button>
          </div>
        </div>

        <p class="text-[10px] text-text2 text-center font-mono uppercase tracking-widest max-sm:tracking-wide break-words leading-snug px-0.5">
          {windowLabel}
        </p>
      </div>
      {#if !hasWorkouts}
        <div class="flex flex-col items-center justify-center py-6 opacity-60">
          <p class="text-xs text-text2">No training distribution data for this selection.</p>
        </div>
      {:else}
        <div class="flex flex-col gap-3">
          <div class="h-6 w-full flex rounded-lg overflow-hidden border border-border/50">
            {#each distribution.pcts as pct, i (i)}
              {@const z = i + 1}
              {@const color = HR_ZONE_HEX[z]}
              <div
                class="h-full transition-all duration-500"
                style="width: {pct}%; background: {color};"
                title="Z{z}: {pct}%"
              ></div>
            {/each}
          </div>

          <div class="grid grid-cols-2 gap-x-4 gap-y-2">
            {#each distribution.pcts as pct, i (i)}
              {@const z = i + 1}
              {@const color = HR_ZONE_HEX[z]}
              {@const label = TIME_IN_ZONES_LABELS[i] ?? `Z{z}`}
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <div class="w-2 h-2 rounded-full" style="background: {color}"></div>
                  <span class="text-[10px] text-text1">{label}</span>
                </div>
                <span class="text-[10px] font-mono font-bold" style="color: {color}">{pct}%</span>
              </div>
            {/each}
          </div>
          
          <p class="text-[10px] text-text2 italic mt-1 text-center break-words leading-snug px-0.5">
            Average distribution across {distribution.validCount} sessions (from {distribution.totalCount} in range). {windowLabel}
          </p>
        </div>
      {/if}
    </Card>

    {#if authStore.tier === 'premium' && hasWorkouts}
      <Card class="!bg-gradient-to-br from-blue/10 via-transparent to-transparent border-blue/20">
        <div class="flex items-center gap-1.5 mb-2">
          <span class="text-[11px] font-mono uppercase tracking-[0.08em] text-blue">Zone Insight</span>
          <Tag color="var(--blue)">ASTRAPHE</Tag>
        </div>
        {#if zonesAnalysisLoading && zonesAnalysisText === null}
          <p class="text-xs text-text2 animate-pulse">Analyzing zone distribution...</p>
        {:else}
          <p class="text-xs text-text1 leading-relaxed">
            {zonesAnalysisText ?? 'Zone insight unavailable — sync more workouts with HR zone data.'}
          </p>
        {/if}
      </Card>
    {/if}
  {/if}
</div>
