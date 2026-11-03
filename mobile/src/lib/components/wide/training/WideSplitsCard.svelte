<script lang="ts">
  /** Splits for one workout (design: WSplits): Chart (power/speed bars + HR line) or Table. */
  import type { ActivitySplit } from '$lib/utils/lapSplits';
  import type { Units } from '$lib/utils/units';
  import { buildSplitChart } from '$lib/utils/splitChart';
  import { splitDistance, splitPace, splitSpeed, splitTime } from '$lib/utils/trainingFormat';

  let { splits, sport, units }: { splits: ActivitySplit[]; sport: string; units: Units } = $props();

  const W = 318;
  const H = 120;
  const chart = $derived(buildSplitChart(splits, W, H));
  let view = $state<'chart' | 'table'>('chart');
  const shown = $derived(chart ? view : 'table');
  const usePace = $derived(sport === 'row' || sport === 'run');
  const showWatts = $derived(splits.some((r) => Number(r.average_watts) > 0));
</script>

<section aria-label="Splits" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-3 min-w-0">
  <div class="flex justify-between items-baseline">
    <h2 class="m-0 font-display font-normal text-[22px]">Splits</h2>
    {#if chart}
      <div role="tablist" aria-label="Split view" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg0 border border-border">
        {#each [['chart', 'Chart'], ['table', 'Table']] as [id, label] (id)}
          <button
            type="button"
            role="tab"
            aria-selected={view === id}
            class="h-7 px-2.5 border-0 rounded-[7px] text-[12px] font-medium cursor-pointer {view === id ? 'bg-border text-text0' : 'bg-transparent text-text2'}"
            onclick={() => (view = id as 'chart' | 'table')}
          >{label}</button>
        {/each}
      </div>
    {/if}
  </div>

  {#if shown === 'chart' && chart}
    <div class="flex flex-col gap-1.5">
      <svg viewBox="0 0 {W} {H}" class="block w-full h-auto" role="img" aria-label="Average {chart.metric} per lap as bars, average heart rate as a line">
        <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} class="stroke-border"></line>
        {#each chart.bars as b, i (i)}
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="3" class="fill-amber"></rect>
        {/each}
        {#if chart.hrLine}
          <polyline points={chart.hrLine} fill="none" class="stroke-red" stroke-width="1.6" stroke-linejoin="round"></polyline>
          {#each chart.bars as b, i (i)}
            {#if b.hy != null}<circle cx={b.cx} cy={b.hy} r="2.5" class="fill-red"></circle>{/if}
          {/each}
        {/if}
      </svg>
      <div class="flex gap-3.5 text-[11px] text-text2">
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2 h-2 rounded-[2px] bg-amber"></span>{chart.metric === 'power' ? 'Avg power' : 'Avg speed'}</span>
        {#if chart.hrLine}<span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3 h-0.5 bg-red"></span>Avg HR</span>{/if}
        <span class="ml-auto">Bar width = lap length</span>
      </div>
    </div>
  {:else}
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
          {#each splits as r (r.split_number)}
            <tr class="border-t border-border text-right font-mono text-xs tabular-nums">
              <th scope="row" class="py-[9px] text-left font-sans font-medium">{r.split_number}</th>
              <td>{splitTime(r.elapsed_time)}</td>
              <td>{splitDistance(r.distance, units)}</td>
              <td>{usePace ? splitPace(r.pace_seconds) : splitSpeed(r, units)}</td>
              <td class="text-text1">{r.average_heartrate ? Math.round(r.average_heartrate) : '—'}</td>
              {#if showWatts}<td>{Number(r.average_watts) > 0 ? Math.round(Number(r.average_watts)) : '—'}</td>{/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
