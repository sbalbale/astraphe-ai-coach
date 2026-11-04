<script lang="ts">
  /**
   * Wide Training log, detail pane (design: WTraining detail, "option D"): map hero when the
   * workout has GPS, the sheet with title, stats and Overview / Charts / Laps / Data tabs.
   * The page owns loading (streams, laps, zones, analysis) and edit / delete / repull.
   */
  import { format } from 'date-fns';
  import GpsTrace from '$lib/components/workout/GpsTrace.svelte';
  import StreamCharts from '$lib/components/workout/StreamCharts.svelte';
  import LapStrip from '$lib/components/workout/LapStrip.svelte';
  import DataSources from '$lib/components/workout/DataSources.svelte';
  import WorkoutPlanPanel from '$lib/components/linking/WorkoutPlanPanel.svelte';
  import WideHrZonesCard from './WideHrZonesCard.svelte';
  import WideSplitsCard from './WideSplitsCard.svelte';
  import WideRecordingCard from './WideRecordingCard.svelte';
  import type { ActivityLap, ActivityStreams, ZoneDef } from '$lib/services/activityService';
  import type { ActivitySplit } from '$lib/utils/lapSplits';
  import { formatElevationMeters, formatWorkoutDistance, type Units } from '$lib/utils/units';
  import { formatAvgPower, getDurationSecs, getWorkoutLabel, positiveRounded, sportGlyph } from '$lib/utils/trainingFormat';

  let {
    workout,
    streams,
    laps,
    splits,
    zoneDefs,
    units,
    use24h = false,
    lthr = 0,
    twoColumn = true,
    loading = false,
    hydrating = false,
    error = null,
    missingPaceStream = false,
    analysis,
    showRepull = false,
    repulling = false,
    onEdit,
    onDelete,
    onRepull
  }: {
    workout: Record<string, any>;
    streams: ActivityStreams | null;
    laps: ActivityLap[];
    splits: ActivitySplit[];
    zoneDefs: ZoneDef[];
    units: Units;
    use24h?: boolean;
    lthr?: number;
    /** Overview / Laps / Data cards side by side (detail pane ≥ ~700 px). */
    twoColumn?: boolean;
    loading?: boolean;
    hydrating?: boolean;
    error?: string | null;
    missingPaceStream?: boolean;
    /** Coach analysis (trial/premium) or the free one-liner. */
    analysis: { premium: boolean; loading: boolean; text: string | null };
    showRepull?: boolean;
    repulling?: boolean;
    onEdit: () => void;
    onDelete: () => void;
    onRepull: () => void;
  } = $props();

  let tab = $state<'overview' | 'charts' | 'laps' | 'data'>('overview');
  $effect(() => {
    void workout?.id;
    tab = 'overview';
  });

  const latlng = $derived(streams?.time_series?.latlng);
  const hasGps = $derived((latlng?.length ?? 0) > 1);
  /** Detail still loading and nothing cached: hold the hero space instead of jumping. */
  const heroPending = $derived(!streams && (loading || hydrating));

  const secs = $derived(getDurationSecs(workout));
  const tss = $derived(positiveRounded(workout?.tss));
  const strain = $derived(positiveRounded(workout?.strain_score));
  const np = $derived(Number(workout?.norm_power_w) || 0);
  const elev = $derived(Number(workout?.elevation_gain_m) || 0);
  const started = $derived(workout?.started_at ? new Date(workout.started_at) : null);
  const kicker = $derived(
    [
      sportGlyph(workout?.sport) === 'OTHER' ? getWorkoutLabel(workout?.sport).toUpperCase() : sportGlyph(workout?.sport),
      started ? format(started, 'EEE d MMM').toUpperCase() : null,
      started ? format(started, use24h ? 'HH:mm' : 'h:mm a') : null
    ]
      .filter(Boolean)
      .join(' · ')
  );
  const title = $derived(workout?.title || `${getWorkoutLabel(workout?.sport)} Session`);

  const tiles = $derived([
    { k: 'Duration', v: `${Math.floor(secs / 3600)}:${String(Math.floor((secs % 3600) / 60)).padStart(2, '0')} h` },
    { k: 'Distance', v: formatWorkoutDistance(workout?.distance_m, units, workout?.sport) },
    { k: 'Avg HR', v: workout?.avg_hr ? String(workout.avg_hr) : '--' },
    { k: 'Avg W', v: formatAvgPower(workout) }
  ]);
  const extras = $derived([
    { k: 'Norm. power', v: np > 0 ? `${np} W` : '--' },
    { k: 'Max HR', v: workout?.max_hr ? String(workout.max_hr) : '--' },
    { k: 'Elevation', v: elev > 0 ? `+${formatElevationMeters(elev, units)}` : '--' }
  ]);

  const askHref = $derived(
    `/chat?prompt=${encodeURIComponent(`About my ${title}${started ? ` on ${format(started, 'EEEE d MMMM')}` : ''}: `)}`
  );

  const TABS = [
    ['overview', 'Overview'],
    ['charts', 'Charts'],
    ['laps', 'Laps'],
    ['data', 'Data']
  ] as const;
  const cols = $derived(twoColumn ? 'grid grid-cols-2 gap-2.5 items-start' : 'flex flex-col gap-2.5');
</script>

{#snippet iconButtons(round: boolean)}
  <button
    type="button"
    aria-label="Edit workout"
    class="{round ? 'w-11 h-11 rounded-full bg-bg0/85' : 'w-10 h-10 rounded-xl bg-transparent'} border border-popover-border text-text0 flex items-center justify-center cursor-pointer"
    onclick={onEdit}
  >
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"></path><path d="m13 7 4 4"></path></svg>
  </button>
  <button
    type="button"
    aria-label="Delete workout"
    class="{round ? 'w-11 h-11 rounded-full bg-bg0/85' : 'w-10 h-10 rounded-xl bg-transparent'} border border-popover-border text-red flex items-center justify-center cursor-pointer"
    onclick={onDelete}
  >
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
  </button>
{/snippet}

<main aria-label="Workout detail" class="flex-1 min-w-0 h-full overflow-y-auto overflow-x-hidden">
  {#if hasGps || heroPending}
    <div class="relative">
      {#if hasGps}
        <GpsTrace
          hero
          heroHeightClass="h-[360px]"
          latlng={latlng}
          heartrate={streams?.time_series?.heartrate}
          time={streams?.time_series?.time}
          zones={zoneDefs}
        />
      {:else}
        <div class="h-[360px] bg-bg1 animate-pulse"></div>
      {/if}
      <div class="absolute right-6 top-5 z-10 flex gap-2">
        {@render iconButtons(true)}
      </div>
    </div>
  {/if}

  <div class="relative px-6 pb-12 flex flex-col gap-4 bg-bg0 {hasGps || heroPending ? '-mt-6 pt-6 rounded-t-[28px] border-t border-border' : 'pt-8'}">
    <header class="flex justify-between items-start gap-4">
      <div class="flex flex-col gap-1.5 min-w-0">
        <span class="font-mono text-[11px] tracking-[0.14em] text-blue">{kicker}</span>
        <h2 class="m-0 font-display font-normal text-[40px] leading-[1.05] break-words">{title}</h2>
      </div>
      <div class="flex-none flex gap-[18px] items-start">
        <span class="flex flex-col items-center"><span class="font-display text-[34px] leading-none">{strain ?? '--'}</span><span class="font-mono text-[9px] text-text2">STRAIN</span></span>
        <span class="flex flex-col items-center"><span class="font-display text-[34px] leading-none">{tss ?? '--'}</span><span class="font-mono text-[9px] text-text2">TSS</span></span>
        {#if !hasGps && !heroPending}
          <span class="flex gap-1.5 ml-1.5">{@render iconButtons(false)}</span>
        {/if}
      </div>
    </header>

    <dl class="m-0 grid grid-cols-4 gap-2">
      {#each tiles as t (t.k)}
        <div class="px-3.5 py-3 rounded-2xl bg-bg2 flex flex-col-reverse gap-0.5 min-w-0">
          <dt class="text-[11px] text-text2">{t.k}</dt>
          <dd class="m-0 text-[18px] font-medium truncate">{t.v}</dd>
        </div>
      {/each}
    </dl>

    <div role="tablist" aria-label="Workout sections" class="grid grid-cols-4 gap-0.5 p-1 rounded-[14px] bg-bg2 border border-border">
      {#each TABS as [id, label] (id)}
        <button
          type="button"
          role="tab"
          aria-selected={tab === id}
          class="h-[38px] border-0 rounded-[10px] text-[14px] font-medium cursor-pointer {tab === id ? 'bg-border text-text0' : 'bg-transparent text-text2'}"
          onclick={() => (tab = id)}
        >{label}</button>
      {/each}
    </div>

    {#if tab === 'overview'}
      <div class={cols}>
        <div class="flex flex-col gap-2.5 min-w-0">
          {#if workout?.id}
            <WorkoutPlanPanel workoutId={String(workout.id)} {streams} />
          {/if}
          <section aria-label="Coach analysis" class="flex flex-col gap-2 p-4 rounded-[20px] bg-bg1 border border-dashed border-popover-border">
            <span class="font-mono text-[10px] tracking-[0.12em] text-blue">{analysis.premium ? 'COACH ANALYSIS' : 'ANALYSIS'}</span>
            {#if analysis.premium}
              {#if analysis.loading && !analysis.text}
                <p class="m-0 text-sm text-text2 animate-pulse">Analyzing workout…</p>
              {:else}
                <p class="m-0 text-[14px] leading-[1.55] text-text1">{analysis.text ?? 'Insight unavailable.'}</p>
              {/if}
              <a href={askHref} class="text-[13px] text-blue no-underline">Ask about this workout</a>
            {:else}
              <p class="m-0 text-[14px] leading-[1.55] text-text1">
                This session added {tss ?? 0} TSS to your acute load. {(tss ?? 0) > 80 ? 'Make recovery a priority tonight.' : 'A good aerobic contribution.'}
              </p>
            {/if}
          </section>
          <dl class="m-0 grid grid-cols-3 gap-2">
            {#each extras as x (x.k)}
              <div class="bg-bg2 border border-border rounded-2xl p-3 flex flex-col-reverse gap-0.5 min-w-0">
                <dt class="text-[11px] text-text2">{x.k}</dt>
                <dd class="m-0 text-[17px] font-medium truncate">{x.v}</dd>
              </div>
            {/each}
          </dl>
        </div>
        <WideHrZonesCard {workout} durationSecs={secs} {zoneDefs} {lthr} />
      </div>
    {/if}

    {#if tab === 'charts'}
      {#if loading || (hydrating && !streams)}
        <div class="rounded-[24px] bg-bg2 animate-pulse h-[320px]"></div>
      {:else if error}
        <p class="m-0 text-[11px] text-red font-mono">{error}</p>
      {:else if streams}
        {#if missingPaceStream}
          <p class="m-0 text-[13px] text-text2 leading-relaxed px-1">Pace stream unavailable for this activity (heart rate is still shown). Try refreshing imported data if streams were imported incorrectly.</p>
        {/if}
        <section aria-label="Power and heart rate" class="bg-bg2 border border-border rounded-[24px] p-[18px] min-h-[260px]">
          <StreamCharts {streams} {laps} sport={workout.sport} zones={zoneDefs} measurementUnits={units} />
        </section>
        <div class="px-4 py-3.5 rounded-[18px] border border-dashed border-popover-border text-[13px] leading-[1.5] text-text1">
          Drag across any chart to select a range. Averages for the selection appear under each chart.
        </div>
      {:else}
        <p class="m-0 text-[13px] text-text2 px-1">No stream data stored for this workout.{#if showRepull} Use “Repull data” on the Data tab to fetch it.{/if}</p>
      {/if}
    {/if}

    {#if tab === 'laps'}
      {#if loading}
        <div class="rounded-[24px] bg-bg2 animate-pulse h-[200px]"></div>
      {:else if laps.length >= 2 || splits.length >= 2}
        <div class={cols}>
          {#if laps.length >= 2}
            <section aria-label="Laps" class="bg-bg2 border border-border rounded-[24px] p-4 min-w-0">
              <LapStrip {laps} sport={workout.sport} zones={zoneDefs} measurementUnits={units} />
            </section>
          {/if}
          {#if splits.length >= 2}
            <WideSplitsCard {splits} sport={workout.sport} {units} />
          {/if}
        </div>
      {:else}
        <p class="m-0 text-[13px] text-text2 px-1">No laps or splits recorded for this workout.</p>
      {/if}
    {/if}

    {#if tab === 'data'}
      <div class={cols}>
        <section aria-label="Data sources" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-4 min-w-0">
          <DataSources {workout} />
          {#if workout.strava_activity_id && workout.strava_streams_fetched === false && !hydrating && !streams}
            <p class="m-0 text-[13px] text-text2 leading-relaxed">Strava is linked, but stream data has not been imported for this workout yet.</p>
          {/if}
          {#if showRepull}
            <button
              type="button"
              class="self-start h-10 px-4 rounded-xl border border-popover-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={repulling || loading}
              onclick={onRepull}
            >{repulling ? 'Pulling data…' : 'Repull data'}</button>
          {/if}
        </section>
        <WideRecordingCard {workout} {streams} {use24h} />
      </div>
    {/if}
  </div>
</main>
