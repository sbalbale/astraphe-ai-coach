<script lang="ts">
  import type { ActivityIntervals } from '$lib/services/activityService';
  import { formatDist, formatHR } from '$lib/utils/formatters';
  import { formatPaceWithSuffix } from '$lib/utils/paceChart';

  let { data }: { data: ActivityIntervals } = $props();

  const intervals = $derived(data.intervals ?? []);

  const bestSplitNum = $derived.by(() => {
    const withPace = intervals.filter((i) => i.pace_per_500m != null);
    if (withPace.length === 0) return null;
    return withPace.reduce((best, cur) =>
      (cur.pace_per_500m ?? Infinity) < (best.pace_per_500m ?? Infinity) ? cur : best
    ).split_number;
  });

  const footer = $derived.by(() => {
    const totalDist = intervals.reduce((s, i) => s + (i.distance ?? 0), 0);
    const totalTime = intervals.reduce((s, i) => s + (i.elapsed_time ?? 0), 0);
    const pace =
      totalDist > 0 && totalTime > 0 ? (totalTime / totalDist) * 500 : null;
    const avgHR =
      intervals.filter((i) => i.average_heartrate != null).length > 0
        ? intervals.reduce((s, i) => s + (i.average_heartrate ?? 0), 0) /
          intervals.filter((i) => i.average_heartrate != null).length
        : null;
    const avgWatts =
      intervals.filter((i) => i.average_watts != null).length > 0
        ? intervals.reduce((s, i) => s + (i.average_watts ?? 0), 0) /
          intervals.filter((i) => i.average_watts != null).length
        : null;
    const avgCadence =
      intervals.filter((i) => i.average_cadence != null).length > 0
        ? intervals.reduce((s, i) => s + (i.average_cadence ?? 0), 0) /
          intervals.filter((i) => i.average_cadence != null).length
        : null;
    return { pace, avgHR, avgWatts, avgCadence };
  });

  const sourceLabel = $derived(
    data.source === 'laps' ? 'Device laps' : data.source === 'stream_derived' ? 'Stream-derived' : data.source
  );
</script>

<div class="bg-glass2 border border-border rounded-2xl p-4 overflow-x-auto">
  <div class="flex items-center justify-between mb-3 gap-2">
    <p class="text-[11px] font-semibold text-text1 font-sans">500m Intervals</p>
    <span class="text-[9px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full bg-teal-dim text-teal border border-teal/30">
      {sourceLabel}
    </span>
  </div>

  {#if intervals.length === 0}
    <p class="text-[12px] text-text2 font-mono text-center py-4">No interval data found.</p>
  {:else}
    <table class="w-full max-w-md table-fixed text-[11px]">
      <colgroup>
        <col class="w-10" />
        <col class="w-[4.25rem]" />
        <col class="w-[5.25rem]" />
        <col class="w-12" />
        <col class="w-12" />
        <col class="w-14" />
      </colgroup>
      <thead>
        <tr class="text-text2 font-mono uppercase text-[9px] tracking-wider border-b border-border">
          <th class="text-left py-2 pr-1">Split #</th>
          <th class="text-right py-2 pr-1">Distance</th>
          <th class="text-right py-2 pr-1">Pace /500m</th>
          <th class="text-right py-2 pr-1">Avg HR</th>
          <th class="text-right py-2 pr-1">Watts</th>
          <th class="text-right py-2">Cadence</th>
        </tr>
      </thead>
      <tbody>
        {#each intervals as row (row.split_number)}
          <tr
            class="border-b border-border/50 font-mono tabular-nums {row.split_number === bestSplitNum
              ? 'bg-[rgba(0,200,168,0.1)] border-l-2 border-l-teal'
              : ''}"
          >
            <td class="py-2 pr-1 text-text1">{row.split_number}</td>
            <td class="py-2 pr-1 text-right text-text1">{formatDist(row.distance)}</td>
            <td class="py-2 pr-1 text-right text-text0 font-semibold">{formatPaceWithSuffix(row.pace_per_500m, 'row')}</td>
            <td class="py-2 pr-1 text-right text-text1">{formatHR(row.average_heartrate)}</td>
            <td class="py-2 pr-1 text-right text-text1">{row.average_watts != null ? Math.round(row.average_watts) : '—'}</td>
            <td class="py-2 text-right text-text1">{row.average_cadence != null ? Math.round(row.average_cadence) : '—'}</td>
          </tr>
        {/each}
        <tr class="text-text2 font-mono text-[10px] border-t border-border">
          <td class="py-2 pr-1 uppercase tracking-wide">Avg</td>
          <td class="py-2 pr-1 text-right">—</td>
          <td class="py-2 pr-1 text-right text-text0 font-semibold">{formatPaceWithSuffix(footer.pace, 'row')}</td>
          <td class="py-2 pr-1 text-right">{formatHR(footer.avgHR)}</td>
          <td class="py-2 pr-1 text-right">{footer.avgWatts != null ? Math.round(footer.avgWatts) : '—'}</td>
          <td class="py-2 text-right">{footer.avgCadence != null ? Math.round(footer.avgCadence) : '—'}</td>
        </tr>
      </tbody>
    </table>
  {/if}
</div>
