<script lang="ts">
  import { formatHR } from '$lib/utils/formatters';
  import {
    coercePaceSport,
    formatPaceWithSuffix,
    formatSpeedFromMps,
    paceDistanceSuffix,
  } from '$lib/utils/paceChart';
  import { formatSegmentDistance, type Units } from '$lib/utils/units';
  import {
    averagePaceFromSplits,
    splitsLabel,
    splitsTableTitle,
    type ActivitySplit,
  } from '$lib/utils/lapSplits';

  let {
    splits,
    sport,
    source = 'laps',
    measurementUnits = 'metric',
  }: {
    splits: ActivitySplit[];
    sport: string;
    source?: string;
    measurementUnits?: Units;
  } = $props();

  const sportKind = $derived(coercePaceSport(sport));
  const labelWord = $derived(splitsLabel(sport));

  const bestSplitNum = $derived.by(() => {
    const withPace = splits.filter((i) => i.pace_seconds != null);
    if (withPace.length === 0) return null;
    return withPace.reduce((best, cur) =>
      (cur.pace_seconds ?? Infinity) < (best.pace_seconds ?? Infinity) ? cur : best
    ).split_number;
  });

  const showPaceCol = $derived(sportKind === 'row' || sportKind === 'run');
  const showSpeedCol = $derived(sportKind === 'bike');
  const showWattsCol = $derived(splits.some((i) => i.average_watts != null));
  const showCadenceCol = $derived(splits.some((i) => i.average_cadence != null));

  const footer = $derived.by(() => {
    const avgHR =
      splits.filter((i) => i.average_heartrate != null).length > 0
        ? splits.reduce((s, i) => s + (i.average_heartrate ?? 0), 0) /
          splits.filter((i) => i.average_heartrate != null).length
        : null;
    const avgWatts =
      splits.filter((i) => i.average_watts != null).length > 0
        ? splits.reduce((s, i) => s + (i.average_watts ?? 0), 0) /
          splits.filter((i) => i.average_watts != null).length
        : null;
    const avgCadence =
      splits.filter((i) => i.average_cadence != null).length > 0
        ? splits.reduce((s, i) => s + (i.average_cadence ?? 0), 0) /
          splits.filter((i) => i.average_cadence != null).length
        : null;
    const speedVals = splits
      .map((i) => i.average_speed)
      .filter((v): v is number => v != null && v > 0);
    const avgSpeed =
      speedVals.length > 0 ? speedVals.reduce((a, b) => a + b, 0) / speedVals.length : null;
    return {
      pace: averagePaceFromSplits(splits, sport, measurementUnits),
      avgHR,
      avgWatts,
      avgCadence,
      avgSpeed,
    };
  });

  const sourceLabel = $derived(
    source === 'laps'
      ? 'Device laps'
      : source === 'stream_derived'
        ? 'Stream-derived'
        : source
  );

  const paceColHeader = $derived(
    sportKind === 'row'
      ? 'Pace /500m'
      : `Pace ${paceDistanceSuffix(sport, measurementUnits)}`
  );
</script>

<div class="w-full bg-glass2 border border-border rounded-2xl p-4">
  <div class="flex items-center justify-between mb-3 gap-2">
    <p class="text-[11px] font-semibold text-text1 font-sans">{splitsTableTitle(sport)}</p>
    <span
      class="text-[9px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full bg-teal-dim text-teal border border-teal/30 shrink-0"
    >
      {sourceLabel}
    </span>
  </div>

  {#if splits.length === 0}
    <p class="text-[12px] text-text2 font-mono text-center py-4">No lap data found.</p>
  {:else}
    <div class="w-full overflow-x-auto">
      <table class="w-full min-w-full text-[11px]">
        <thead>
          <tr class="text-text2 font-mono uppercase text-[9px] tracking-wider border-b border-border">
            <th class="text-left py-2 pr-2 w-[10%]">{labelWord} #</th>
            <th class="text-right py-2 pr-2">Distance</th>
            {#if showPaceCol}
              <th class="text-right py-2 pr-2">{paceColHeader}</th>
            {/if}
            {#if showSpeedCol}
              <th class="text-right py-2 pr-2">Avg speed</th>
            {/if}
            <th class="text-right py-2 pr-2">Avg HR</th>
            {#if showWattsCol}
              <th class="text-right py-2 pr-2">Watts</th>
            {/if}
            {#if showCadenceCol}
              <th class="text-right py-2">Cadence</th>
            {/if}
          </tr>
        </thead>
        <tbody>
          {#each splits as row (row.split_number)}
            <tr
              class="border-b border-border/50 font-mono tabular-nums {row.split_number === bestSplitNum
                ? 'bg-[rgba(0,200,168,0.1)] border-l-2 border-l-teal'
                : ''}"
            >
              <td class="py-2 pr-2 text-text1">{row.split_number}</td>
              <td class="py-2 pr-2 text-right text-text1"
                >{formatSegmentDistance(row.distance, measurementUnits, sport)}</td
              >
              {#if showPaceCol}
                <td class="py-2 pr-2 text-right text-text0 font-semibold"
                  >{formatPaceWithSuffix(row.pace_seconds, sport, measurementUnits)}</td
                >
              {/if}
              {#if showSpeedCol}
                <td class="py-2 pr-2 text-right text-text0 font-semibold"
                  >{formatSpeedFromMps(row.average_speed, measurementUnits)}</td
                >
              {/if}
              <td class="py-2 pr-2 text-right text-text1">{formatHR(row.average_heartrate)}</td>
              {#if showWattsCol}
                <td class="py-2 pr-2 text-right text-text1"
                  >{row.average_watts != null ? Math.round(row.average_watts) : '—'}</td
                >
              {/if}
              {#if showCadenceCol}
                <td class="py-2 text-right text-text1"
                  >{row.average_cadence != null ? Math.round(row.average_cadence) : '—'}</td
                >
              {/if}
            </tr>
          {/each}
          <tr class="text-text2 font-mono text-[10px] border-t border-border">
            <td class="py-2 pr-2 uppercase tracking-wide">Avg</td>
            <td class="py-2 pr-2 text-right">—</td>
            {#if showPaceCol}
              <td class="py-2 pr-2 text-right text-text0 font-semibold"
                >{formatPaceWithSuffix(footer.pace, sport, measurementUnits)}</td
              >
            {/if}
            {#if showSpeedCol}
              <td class="py-2 pr-2 text-right text-text0 font-semibold"
                >{formatSpeedFromMps(footer.avgSpeed, measurementUnits)}</td
              >
            {/if}
            <td class="py-2 pr-2 text-right">{formatHR(footer.avgHR)}</td>
            {#if showWattsCol}
              <td class="py-2 pr-2 text-right"
                >{footer.avgWatts != null ? Math.round(footer.avgWatts) : '—'}</td
              >
            {/if}
            {#if showCadenceCol}
              <td class="py-2 text-right"
                >{footer.avgCadence != null ? Math.round(footer.avgCadence) : '—'}</td
              >
            {/if}
          </tr>
        </tbody>
      </table>
    </div>
  {/if}
</div>
