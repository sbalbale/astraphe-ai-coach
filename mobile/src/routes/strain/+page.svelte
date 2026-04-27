<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  const strainData = [
    { label: 'Cardiovascular', value: 85, color: '#F07178', desc: 'Heart rate response vs expected based on power/pace.' },
    { label: 'Muscular', value: 42, color: '#FFCB88', desc: 'Estimated lower body tissue damage from recent volume.' },
    { label: 'Nervous System', value: 68, color: '#4621FF', desc: 'Derived from HRV and high-intensity interval frequency.' }
  ];
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Physical Tolerance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Strain</h1>
  </div>

  <!-- Overview -->
  <Card style="background: linear-gradient(135deg, rgba(255,203,136,0.12), transparent); border-color: rgba(255,203,136,0.3);">
    <div class="flex items-center gap-4">
      <RadialProgress value={athleteStore.atl} max={120} size={64} color="var(--amber)" label={athleteStore.atl.toString()} sub="ATL" />
      <div class="flex-1">
        <p class="text-[15px] font-semibold mb-1">Acute Load (Fatigue)</p>
        <p class="text-xs text-text1 leading-relaxed">Your 7-day average stress is {athleteStore.atl}. This is {athleteStore.atl > 60 ? 'high' : athleteStore.atl > 30 ? 'moderate' : 'low'} compared to your historical baseline.</p>
      </div>
    </div>
  </Card>

  <!-- Component Breakdown -->
  <Card>
    <p class="text-[13px] font-semibold mb-3">Strain Components</p>
    <div class="flex flex-col gap-3">
      {#each strainData as s}
        <div>
          <div class="flex justify-between items-center mb-1.5">
            <span class="text-xs font-semibold">{s.label}</span>
            <span class="text-[12px] font-bold font-mono" style="color: {s.color}">{s.value}<span class="text-[9px] font-normal text-text2">/100</span></span>
          </div>
          <div class="h-1.5 bg-glass2 rounded-sm overflow-hidden mb-1.5">
            <div class="h-full rounded-sm" style="width: {s.value}%; background: {s.color}"></div>
          </div>
          <p class="text-[10px] text-text2 leading-relaxed">{s.desc}</p>
        </div>
      {/each}
    </div>
  </Card>

  <!-- Load Context -->
  {#if athleteStore.metrics?.trainingLoadData}
    <Card>
      <p class="text-[13px] font-semibold mb-2">Fatigue Accumulation</p>
      <p class="text-[11px] text-text2 mb-3">ATL vs CTL over the last 7 days.</p>
      <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
    </Card>
  {/if}

  <!-- AI Insight -->
  <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.12), transparent);">
    <p class="text-[13px] font-semibold mb-1.5">Coach's Note</p>
    <p class="text-xs text-text1 leading-relaxed">Cardiovascular strain is high following yesterday's interval block, but muscular strain remains low. Today's easy Z2 run is perfectly positioned to promote blood flow without adding mechanical stress.</p>
  </Card>
</div>
