<script module lang="ts">
  import { WEEK_STARTS_ON } from '$lib/utils/week';
  import { SvelteMap } from 'svelte/reactivity';
  const zonesAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import { workoutDurationSecs } from '$lib/utils/workoutDuration';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import DashedNote from '$lib/components/ui/DashedNote.svelte';
  import { goto } from '$app/navigation';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';
  import MonthNavigator from '$lib/components/MonthNavigator.svelte';
  import WeekNavigator from '$lib/components/WeekNavigator.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
  import { HR_ZONE_HEX, HR_ZONE_LABELS } from '$lib/hrZoneDisplay';
  import {
    addDays,
    addMonths,
    endOfDay,
    endOfMonth,
    format,
    isWithinInterval,
    endOfWeek,
    startOfDay,
    startOfMonth,
    startOfWeek,
    subDays
  } from 'date-fns';

  let sport = $state('all');

  type WindowMode = 'week' | 'month';
  let windowMode = $state<WindowMode>('week');

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

  /** Descriptions by zone number — API returns exactly five HR zones for every method */
  const ZONE_DESCRIPTIONS: Record<number, string> = {
    1: 'Recovery and very easy aerobic work.',
    2: 'Steady endurance. Aerobic base and fat metabolism.',
    3: 'Moderate-hard. Tempo and sustainable hard efforts.',
    4: 'Threshold. Race-pace sustainable intensity.',
    5: 'VO2max+. Hard intervals and short maximal efforts.'
  };

  const hasProfile = $derived(!!athleteStore.profile);

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

  /** Zone Definitions card: high intensity first (Z5 → Z1). */
  let zones = $derived([...hrZones].sort((a, b) => b.zone - a.zone));

  
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
      // Monday–Sunday calendar week containing the selected day
      return startOfDay(startOfWeek(parseDateInputLocal(selectedDay), { weekStartsOn: WEEK_STARTS_ON }));
    }
    const monthDate = new Date(`${selectedMonth}-01T00:00:00`);
    return startOfMonth(monthDate);
  });

  // Load older workouts when this week / month reaches back past what's loaded (the store
  // starts with the newest 200, so earlier months showed "No heart-rate zone data").
  $effect(() => {
    const day = format(windowStart, 'yyyy-MM-dd');
    untrack(() => {
      void athleteStore.ensureWorkoutsFrom(day);
    });
  });

  const windowEnd = $derived.by(() => {
    if (windowMode === 'week') {
      return endOfDay(endOfWeek(parseDateInputLocal(selectedDay), { weekStartsOn: WEEK_STARTS_ON }));
    }
    const monthDate = new Date(`${selectedMonth}-01T00:00:00`);
    return endOfMonth(monthDate);
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

  // --- Design view: time per zone, definitions with power ranges ---
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);
  const lthr = $derived(Number((athleteStore.profile as any)?.lthr ?? (athleteStore.profile as any)?.threshold_hr) || 0);
  const fmtDuration = (secs: number) => {
    const m = Math.round(secs / 60);
    if (m <= 0) return '0m';
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
  };
  const zoneSeconds = $derived.by(() => {
    const totals = [0, 0, 0, 0, 0];
    for (const w of timeAndSportFilteredWorkouts as any[]) {
      if (w.hr_zone_1_pct === null || w.hr_zone_1_pct === undefined) continue;
      const secs = workoutDurationSecs(w) ?? 0;
      for (let z = 0; z < 5; z++) totals[z] += (secs * (Number(w[`hr_zone_${z + 1}_pct`]) || 0)) / 100;
    }
    return totals;
  });
  // Coggan power zones as % of FTP (upper bound of each zone).
  const POWER_ZONE_UPPER_PCT = [0.55, 0.75, 0.9, 1.05];
  const zoneRows = $derived.by(() => {
    const total = zoneSeconds.reduce((a, b) => a + b, 0);
    return [...hrZones]
      .sort((a: any, b: any) => a.zone - b.zone)
      .map((z: any) => {
        const secs = zoneSeconds[z.zone - 1] ?? 0;
        const hr = z.hi >= 500 ? `≥ ${z.lo}` : z.lo <= 0 ? `< ${z.hi + 1}` : `${z.lo}–${z.hi}`;
        const lo = ftp && z.zone > 1 ? Math.round(ftp * POWER_ZONE_UPPER_PCT[z.zone - 2]) + 1 : 0;
        const hi = ftp && z.zone <= 4 ? Math.round(ftp * POWER_ZONE_UPPER_PCT[z.zone - 1]) : 0;
        const watts = !ftp ? '—' : z.zone === 1 ? `< ${hi + 1} W` : z.zone === 5 ? `≥ ${lo} W` : `${lo}–${hi}`;
        return { zone: z.zone, name: z.name, color: z.color, hr, watts, secs, time: fmtDuration(secs), pct: total > 0 ? Math.round((secs / total) * 100) : 0 };
      });
  });
  const zoneSummary = $derived.by(() => {
    const total = zoneSeconds.reduce((a, b) => a + b, 0);
    if (total === 0) return "Log a few heart-rate workouts and your zone split will show up here.";
    const easy = zoneRows.filter((z) => z.zone <= 2).reduce((a, z) => a + z.pct, 0);
    const hard = 100 - easy;
    const verdict = easy >= 75 ? "close to a polarized split" : easy >= 60 ? "a moderate-leaning split" : "heavy on intensity";
    return `${easy}% easy, ${hard}% at tempo or above — ${verdict}. ${fmtDuration(total)} recorded.`;
  });

  // Wide layouts show zones on the combined Trends & zones page.
  $effect(() => {
    if (viewport.wide) void goto('/trends', { replaceState: true, keepFocus: true, noScroll: true });
  });

  $effect(() => {
    pageHeader.eyebrow = 'Heart rate & power';
    pageHeader.segments = [{ value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }];
    pageHeader.segment = windowMode;
    pageHeader.onSegment = (v) => (windowMode = v as WindowMode);
    return resetPageHeader;
  });
</script>

<div class="flex flex-col gap-3.5">
  {#if athleteStore.loading && !athleteStore.initialLoadDone}
    <div class="flex-1 flex flex-col items-center justify-center py-20 opacity-40">
      <div class="w-6 h-6 border-2 border-blue border-t-transparent rounded-full animate-spin mb-4"></div>
      <p class="text-[10px] font-mono tracking-widest uppercase">Syncing Biometrics...</p>
    </div>
  {:else if !hasProfile || !hasZoneDefinitions}
    <EmptyStateCard
      icon="gauge"
      tone="blue"
      eyebrow="Not set up"
      title="Set your thresholds"
      message="Zones need your max or lactate-threshold heart rate, plus FTP for power zones. Not sure? Your coach can estimate them from your recent rides."
      actionLabel="Estimate from my rides"
      onAction={() => goto(`/chat?prompt=${encodeURIComponent('Estimate my max heart rate, threshold heart rate and FTP from my last 6 weeks of rides.')}`)}
      secondaryLabel="Enter them myself"
      onSecondary={() => goto('/profile/training-settings')}
    />
    <DashedNote>
      <div class="flex flex-col gap-3.5 py-1" aria-hidden="true">
        {#each [1, 2, 3, 4, 5] as zn (zn)}
          <div class="flex items-center gap-4">
            <span class="w-6 font-mono text-[13px] text-text2">Z{zn}</span>
            <div class="flex-1 h-2.5 rounded-full bg-bg3"></div>
          </div>
        {/each}
      </div>
    </DashedNote>
  {:else}
    <!-- Distribution -->
    <section aria-label="Distribution" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3">
      {#if windowMode === 'month'}
        <MonthNavigator bind:value={selectedMonth} max={todayMonthMax} subtitle="This month · so far" />
      {:else}
        <WeekNavigator bind:value={selectedDay} max={todayDayMax} />
      {/if}
      {#if zoneRows.every((z) => z.secs === 0)}
        <p class="m-0 text-[13px] text-text2">No heart-rate zone data for this period yet.</p>
      {/if}
      {#each zoneRows as z (z.zone)}
        <div class="flex items-center gap-2.5">
          <span class="w-[26px] font-mono text-xs text-text1">Z{z.zone}</span>
          <div aria-hidden="true" class="flex-1 h-2.5 rounded-[5px] bg-bg3 overflow-hidden">
            <div class="h-2.5 rounded-[5px]" style="width: {Math.max(z.pct * 1.8, z.secs > 0 ? 4 : 0)}%; background: {z.color}"></div>
          </div>
          <span class="w-12 text-right font-mono text-xs">{z.time}</span>
          <span class="w-[34px] text-right font-mono text-xs text-text2">{z.pct}%</span>
        </div>
      {/each}
    </section>

    <!-- Definitions -->
    <section aria-label="Zone definitions" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col">
      <div class="flex justify-between items-baseline pb-2">
        <h2 class="m-0 font-display font-normal text-[22px]">Your zones</h2>
        <span class="font-mono text-[11px] text-text2">{#if lthr}LTHR {lthr}{/if}{#if lthr && ftp} · {/if}{#if ftp}FTP {ftp}{/if}</span>
      </div>
      {#each zoneRows as z (z.zone)}
        <div class="grid grid-cols-[14px_1fr_auto_auto] gap-2.5 items-center py-[9px] border-t border-border text-[13px]">
          <span aria-hidden="true" class="w-2.5 h-2.5 rounded-[3px]" style="background: {z.color}"></span>
          <span>{z.name}</span>
          <span class="font-mono text-xs text-text1">{z.hr}</span>
          <span class="w-16 text-right font-mono text-xs text-text1">{z.watts}</span>
        </div>
      {/each}
    </section>

    <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-border">
      <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">ZONES</span>
      <span class="text-[13px] leading-[1.45] text-text1">
        {#if zonesAnalysisLoading && zonesAnalysisText === null}Analyzing…{:else}
          {zonesAnalysisText ?? zoneSummary}
        {/if}
      </span>
    </div>
  {/if}
</div>
