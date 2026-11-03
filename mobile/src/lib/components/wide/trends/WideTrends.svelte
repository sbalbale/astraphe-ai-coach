<script lang="ts">
  import { WEEK_STARTS_ON } from '$lib/utils/week';
  /**
   * Wide (tablet / desktop) Trends & zones (design: WTrends): stat tiles, training load,
   * weekly TSS and time in zones side by side. Selecting a week in either chart also
   * points the zones panel at that week.
   */
  import { onMount } from 'svelte';
  import { addDays, differenceInCalendarDays, format, startOfWeek } from 'date-fns';
  import { api } from '$lib/api';
  import type { Workout } from '$lib/types/training';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { formCssColor } from '$lib/scoreColors';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import LoadChart from './LoadChart.svelte';
  import WeeklyTssChart from './WeeklyTssChart.svelte';
  import ZonesPanel from './ZonesPanel.svelte';
  import { rampRatePerWeek, rangeStart, weeklyBuckets, type LoadRow, type ZonePeriod } from './trendsWide';

  /** Weeks shown (6, 12 or 26); the page's header tabs drive it. */
  let { range }: { range: number } = $props();

  const MAX_WEEKS = 26;
  const today = new Date();
  let rows = $state<LoadRow[]>([]);
  let planned = $state<Workout[]>([]);
  let loaded = $state(false);

  onMount(async () => {
    athleteStore.fetchAll();
    const start = format(rangeStart(today, MAX_WEEKS), 'yyyy-MM-dd');
    const end = format(addDays(startOfWeek(today, { weekStartsOn: WEEK_STARTS_ON }), 6), 'yyyy-MM-dd');
    const [metrics, plan] = await Promise.all([
      api.get<{ trainingLoadData?: LoadRow[] }>(`/v1/athlete/metrics?start_date=${start}&end_date=${format(today, 'yyyy-MM-dd')}`),
      api.getWorkouts(start, end)
    ]);
    rows = metrics?.trainingLoadData ?? [];
    planned = plan ?? [];
    loaded = true;
  });

  const weeks = $derived(weeklyBuckets(rows, planned, range, today));
  /** Selected week as weeks before the current one (stable across range changes). */
  let selBack = $state(0);
  const sel = $derived(Math.max(0, weeks.length - 1 - selBack));

  let zonePeriod = $state<ZonePeriod>('week');
  let zoneOffset = $state(0);
  function selectWeek(i: number) {
    const w = weeks[i];
    if (!w) return;
    selBack = Math.round(differenceInCalendarDays(startOfWeek(today, { weekStartsOn: WEEK_STARTS_ON }), w.start) / 7);
    zonePeriod = 'week';
    zoneOffset = -selBack;
  }
  // Paging the zones panel by week moves the chart selection with it.
  $effect(() => {
    if (zonePeriod === 'week') selBack = -zoneOffset;
  });

  const latest = $derived(rows.length ? [...rows].sort((a, b) => a.date.localeCompare(b.date))[rows.length - 1] : null);
  const ramp = $derived(rampRatePerWeek(rows));
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);
  const lthr = $derived(Number((athleteStore.profile as any)?.lthr ?? (athleteStore.profile as any)?.threshold_hr) || 0);
  const hrZones = $derived(athleteStore.profile?.hr_zones?.zones ?? []);

  const fmt1 = (n: number | null | undefined) => (n == null || !Number.isFinite(Number(n)) ? '--' : Number(n).toFixed(1));
  const tsb = $derived(latest ? (latest.tsb ?? (Number(latest.ctl) || 0) - (Number(latest.atl) || 0)) : null);
  const tiles = $derived([
    { k: 'Fitness', sub: 'CTL', v: fmt1(latest?.ctl), color: '' },
    { k: 'Fatigue', sub: 'ATL', v: fmt1(latest?.atl), color: '' },
    { k: 'Form', sub: 'TSB', v: tsb == null ? '--' : `${tsb > 0 ? '+' : ''}${tsb.toFixed(1)}`, color: tsb == null ? '' : formCssColor(tsb) },
    { k: 'FTP', sub: lthr ? `LTHR ${lthr}` : '', v: ftp ? `${ftp} W` : '--', color: '' },
    { k: 'Ramp rate', sub: '4 WK', v: ramp == null ? '--' : `${ramp > 0 ? '+' : ''}${ramp.toFixed(1)}/wk`, color: '' }
  ]);
</script>

{#if loaded && rows.length === 0}
  <EmptyStateCard icon="pulse" eyebrow="Nothing yet" title="No trends yet" message="Fitness and fatigue trends appear once a few weeks of workouts have synced or been logged." />
{:else}
  <div class="flex-1 min-h-0 flex flex-col gap-5">
    <dl class="m-0 grid grid-cols-5 gap-2.5">
      {#each tiles as t (t.k)}
        <div class="bg-bg2 border border-border rounded-[18px] px-4 py-3.5 flex flex-col-reverse gap-1 min-w-0">
          <dt class="flex justify-between gap-2 text-[12px] text-text2"><span>{t.k}</span><span class="text-text3 truncate">{t.sub}</span></dt>
          <dd class="m-0 text-[26px] font-medium tracking-[-0.02em] truncate {t.color ? '' : 'text-text0'}" style={t.color ? `color: ${t.color}` : undefined}>{t.v}</dd>
        </div>
      {/each}
    </dl>

    <!-- Two columns from ~1100 px; stacked on narrower wide screens (iPad portrait). -->
    <div class="flex-1 min-h-0 grid gap-4 grid-cols-1 min-[1100px]:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <div class="flex flex-col gap-4 min-h-0">
        {#if loaded}
          <LoadChart {weeks} selected={sel} onselect={selectWeek} />
          <WeeklyTssChart {weeks} selected={sel} onselect={selectWeek} />
        {:else}
          <div class="h-[290px] rounded-[24px] bg-bg2 animate-pulse"></div>
          <div class="h-[240px] rounded-[24px] bg-bg2 animate-pulse"></div>
        {/if}
      </div>
      <ZonesPanel workouts={athleteStore.workouts} {hrZones} {ftp} {lthr} {today} bind:period={zonePeriod} bind:offset={zoneOffset} />
    </div>
  </div>
{/if}
