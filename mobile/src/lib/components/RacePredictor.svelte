<script lang="ts">
  import Card from '$lib/components/Card.svelte';

  let { ctl = 68 } = $props<{
    ctl?: number;
  }>();

  const rows = [
    { label: 'Marathon', delta: '↓ 4:12 from last prediction', time: '2:58:40', timeClass: 'text-teal' },
    { label: 'Half Marathon', delta: '↓ 1:44 from last prediction', time: '1:23:10', timeClass: 'text-blue' },
    { label: '10K', delta: '↑ 0:18 from last prediction', time: '37:05', timeClass: 'text-teal' },
    { label: '5K', delta: '↑ 0:05 from last prediction', time: '17:52', timeClass: 'text-amber' }
  ] as const;
</script>

<Card>
  <div class="flex justify-between items-center mb-4">
    <div class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">RACE PREDICTOR</div>
    <div class="flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full bg-teal animate-pulse" aria-hidden="true"></span>
      <span class="text-[10px] text-teal font-mono">LIVE</span>
    </div>
  </div>

  <div class="flex flex-col gap-3">
    {#each rows as row (row.label)}
      <div class="p-4 rounded-xl border border-border bg-glass2 flex justify-between items-center">
        <div>
          <p class="font-bold text-sm text-text0">{row.label}</p>
          <p class="text-[11px] text-text2 mt-1">{row.delta}</p>
        </div>
        <div class="font-mono text-xl font-bold {row.timeClass}">{row.time}</div>
      </div>
    {/each}
  </div>

  <div class="border border-blue/30 bg-blue/5 rounded-xl p-4 mt-2">
    <div class="flex items-center gap-2 text-[10px] text-blue font-mono uppercase tracking-wider">
      <span class="w-1.5 h-1.5 rounded-full bg-blue" aria-hidden="true"></span>
      <span>RACE PREDICTOR · BASED ON CTL {ctl}</span>
    </div>
    <p class="text-xs text-text1 leading-relaxed mt-2">
      Predictions derived from VO2 proxy metrics, pace distribution, and 90-day training trajectory. Updated after every activity.
    </p>
  </div>
</Card>
