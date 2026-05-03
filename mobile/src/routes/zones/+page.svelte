<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import MonthPicker from '$lib/components/MonthPicker.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
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

  const hasProfile = $derived(!!athleteStore.profile);
  
  // Fallbacks if profile not loaded
  const maxHR = $derived(athleteStore.profile?.max_hr || 190);
  const restingHR = $derived(athleteStore.profile?.resting_hr || 50);
  const hrr = $derived(maxHR - restingHR);

  const hrZones = $derived([
    { zone: 0, name: 'Resting', lo: 0, hi: Math.max(0, Math.round(restingHR + hrr * 0.5) - 1), color: '#AAB3BF', desc: 'Very easy. Below Zone 1.' },
    { zone: 1, name: 'Recovery', lo: Math.round(restingHR + hrr * 0.5), hi: Math.round(restingHR + hrr * 0.6), color: '#4621FF', desc: 'Active recovery. Minimal stress.' },
    { zone: 2, name: 'Aerobic', lo: Math.round(restingHR + hrr * 0.6) + 1, hi: Math.round(restingHR + hrr * 0.7), color: '#00C8A8', desc: 'Endurance. Optimized for fat metabolism.' },
    { zone: 3, name: 'Tempo', lo: Math.round(restingHR + hrr * 0.7) + 1, hi: Math.round(restingHR + hrr * 0.8), color: '#FFCB88', desc: 'Moderate. Improving aerobic capacity.' },
    { zone: 4, name: 'Threshold', lo: Math.round(restingHR + hrr * 0.8) + 1, hi: Math.round(restingHR + hrr * 0.9), color: '#F07178', desc: 'Hard. Lactate threshold development.' },
    { zone: 5, name: 'VO2max', lo: Math.round(restingHR + hrr * 0.9) + 1, hi: maxHR, color: '#FF4791', desc: 'Max effort. Building peak power.' },
  ]);
  
  let zones = $derived(hrZones);

  
  // Filter activities
  const sportOptions = [
    { id: 'all', label: '🌍 Overview' },
    { id: 'run', label: '🏃 Run' },
    { id: 'bike', label: '🚴 Bike' },
    { id: 'swim', label: '🏊 Swim' },
    { id: 'strength', label: '💪 Strength' },
    { id: 'rowing', label: '🚣 Row' },
    { id: 'other', label: '🏁 Other' }
  ];

  const sportFilteredWorkouts = $derived(
    sport === 'all' 
      ? athleteStore.workouts 
      : athleteStore.workouts.filter(w => {
          const s = w.sport?.toLowerCase();
          // Backward compatibility for older rows.
          if (sport === 'strength') return s === 'strength' || s === 'strength_training' || s === 'gym';
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

  // Memoize distribution calculation
  const distribution = $derived.by(() => {
    if (!hasWorkouts) return { pcts: [0, 0, 0, 0, 0, 0] as number[], validCount: 0, totalCount: 0 };
    
    let totals = [0, 0, 0, 0, 0, 0];
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
        const z0 = Math.max(0, 100 - (z1 + z2 + z3 + z4 + z5));

        totals[0] += z0;
        totals[1] += z1;
        totals[2] += z2;
        totals[3] += z3;
        totals[4] += z4;
        totals[5] += z5;
        validCount++;
      }
    }
    
    if (validCount === 0) {
      return { pcts: [0, 0, 0, 0, 0, 0] as number[], validCount: 0, totalCount: timeAndSportFilteredWorkouts.length };
    }
    
    const count = validCount;
    
    // Normalize to sum to exactly 100%
    let rounded = totals.map(t => Math.round(t / count));
    let sum = rounded.reduce((a, b) => a + b, 0);
    
    if (sum !== 100 && sum > 0) {
      // Adjust the largest zone to make it exactly 100%
      let maxIdx = rounded.indexOf(Math.max(...rounded));
      rounded[maxIdx] += (100 - sum);
    }
    
    return { pcts: rounded, validCount, totalCount: timeAndSportFilteredWorkouts.length };
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Heart Rate & Power</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Zones</h1>
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
  {:else}
    <!-- Sport toggle -->
    <div class="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar shrink-0">
      {#each sportOptions as s (s.id)}
        <Pill active={sport === s.id} onclick={() => sport = s.id}>
          {s.label}
        </Pill>
      {/each}
    </div>

    <!-- Anchor values -->
    <div class="grid grid-cols-2 gap-2.5">
      <Card style="background: linear-gradient(135deg, rgba(240,113,120,0.12), transparent);">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Max Heart Rate</p>
        <p class="text-[26px] font-bold text-red tracking-[-0.02em] leading-tight">
          {maxHR}
          <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
        </p>
        <p class="text-[10px] text-text2 mt-0.5">Profile Baseline</p>
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
        <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em] mb-1">Resting Heart Rate</p>
        <p class="text-[26px] font-bold text-[#4621FF] tracking-[-0.02em] leading-tight">
          {restingHR}
          <span class="text-[13px] font-normal text-text2 ml-1">bpm</span>
        </p>
        <p class="text-[10px] text-text2 mt-0.5">HRR: {hrr} bpm</p>
      </Card>
    </div>

    <!-- Zone Bars -->
    <Card>
      <p class="text-[13px] font-semibold mb-3.5">Zone Definitions</p>
      <div class="flex flex-col gap-2.5">
        {#each zones as z, i (z.zone)}
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
                  <span class="text-[11px] font-mono" style="color: {z.color}">{z.lo}–{z.hi} bpm</span>
                </div>
                <div class="h-1.25 bg-glass2 rounded overflow-hidden">
                  <div class="h-full rounded" 
                       style="width: {((z.hi - z.lo) / maxHR) * 100}%; margin-left: {(z.lo / maxHR) * 100}%; background: {z.color};"></div>
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
      <div class="flex flex-col gap-2.5 mb-3">
        <div class="flex items-center gap-2">
          <div class="flex bg-glass2 border border-border/50 rounded-lg overflow-hidden shrink-0">
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

          <div class="ml-auto flex items-center gap-1.5">
            <button
              class="w-7 h-7 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors flex items-center justify-center text-text1"
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
              <div class="w-[130px]">
                <DatePicker
                  id="zones-week"
                  bind:value={dayPickerValue}
                  max={todayDayMax}
                  ariaLabel="Select end date"
                  buttonClass="h-7 px-2 pr-2 rounded-lg bg-glass2 border border-border/50 text-[10px] font-mono text-text1"
                />
              </div>
            {:else}
              <div class="w-[130px]">
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
              class="h-7 px-2 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors text-[10px] font-mono text-text1"
              onclick={jumpToToday}
              type="button"
              aria-label="Jump to current week/month"
              title="Today"
            >
              Today
            </button>

            <button
              class="w-7 h-7 rounded-lg bg-glass2 border border-border/50 transition-colors flex items-center justify-center text-text1 {canGoForward ? 'hover:bg-glass' : 'opacity-40 cursor-not-allowed'}"
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

        <p class="text-[10px] text-text2 text-center font-mono tracking-widest uppercase">
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
              {@const colors = ['#AAB3BF', '#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791']}
              <div class="h-full transition-all duration-500" style="width: {pct}%; background: {colors[i]};" title="Z{i+1}: {pct}%"></div>
            {/each}
          </div>
          
          <div class="grid grid-cols-2 gap-x-4 gap-y-2">
            {#each distribution.pcts as pct, i (i)}
              {@const colors = ['#AAB3BF', '#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791']}
              {@const labels = ['Z0 Resting', 'Z1 Recovery', 'Z2 Aerobic', 'Z3 Tempo', 'Z4 Threshold', 'Z5 VO2max']}
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <div class="w-2 h-2 rounded-full" style="background: {colors[i]}"></div>
                  <span class="text-[10px] text-text1">{labels[i]}</span>
                </div>
                <span class="text-[10px] font-mono font-bold" style="color: {colors[i]}">{pct}%</span>
              </div>
            {/each}
          </div>
          
          <p class="text-[10px] text-text2 italic mt-1 text-center">
            Average distribution across {distribution.validCount} sessions (from {distribution.totalCount} in range). {windowLabel}
          </p>
        </div>
      {/if}
    </Card>
  {/if}
</div>
