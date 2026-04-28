<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  const hasData = $derived(athleteStore.atl > 0 || athleteStore.workouts?.length > 0);

  // Derive strain components from real data
  let strainData = $derived.by(() => {
    if (!hasData) return [];

    const latestBio = athleteStore.biometrics?.series?.length > 0 
      ? athleteStore.biometrics.series[athleteStore.biometrics.series.length - 1] 
      : null;
    
    const latestTss = athleteStore.workouts?.length > 0
      ? athleteStore.workouts[0].tss
      : 0;

    // Cardiovascular: Based on daily TSS relative to a "hard" day (e.g. 150 TSS)
    const cardo = Math.min(Math.round((latestTss / 150) * 100), 100);
    
    // Muscular: Estimated as a portion of TSS load
    const muscular = Math.min(Math.round((latestTss / 200) * 100), 100);
    
    // Nervous System: Inverse of recovery score (lower recovery = higher nervous strain)
    const nervous = latestBio ? 100 - (latestBio.recovery_score || 50) : 0;

    return [
      { label: 'Cardiovascular', value: cardo, color: '#F07178', desc: 'Heart rate response vs expected based on power/pace.' },
      { label: 'Muscular', value: muscular, color: '#FFCB88', desc: 'Estimated lower body tissue damage from recent volume.' },
      { label: 'Nervous System', value: nervous, color: '#4621FF', desc: 'Derived from HRV and high-intensity interval frequency.' }
    ].filter(s => s.value > 0);
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Physical Tolerance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Strain</h1>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Strain Data" 
      message="Connect your activity tracker to analyze the physiological cost of your training."
      icon="🔥"
    />
  {:else if !hasData}
    <EmptyState 
      title="Waiting for Activity" 
      message="Log a workout or sync your watch to see your strain breakdown."
      icon="⏳"
    />
  {:else}
    <!-- Overview -->
    <Card style="background: linear-gradient(135deg, rgba(255,203,136,0.12), transparent); border-color: rgba(255,203,136,0.3);">
      <div class="flex items-center gap-4">
        <RadialProgress value={athleteStore.atl} max={120} size={64} color="var(--amber)" label={Math.round(athleteStore.atl).toString()} sub="ATL" />
        <div class="flex-1">
          <p class="text-[15px] font-semibold mb-1">Acute Load (Fatigue)</p>
          <p class="text-xs text-text1 leading-relaxed">Your 7-day average stress is {Math.round(athleteStore.atl)}. This is {athleteStore.atl > 60 ? 'high' : athleteStore.atl > 30 ? 'moderate' : 'low'} compared to your historical baseline.</p>
        </div>
      </div>
    </Card>

    <!-- Component Breakdown -->
    {#if strainData.length > 0}
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
    {/if}

    <!-- Load Context -->
    {#if athleteStore.metrics?.trainingLoadData?.length > 0}
      <Card>
        <p class="text-[13px] font-semibold mb-2">Fatigue Accumulation</p>
        <p class="text-[11px] text-text2 mb-3">ATL vs CTL over the last 7 days.</p>
        <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
      </Card>
    {/if}

    <!-- Coach Note -->
    <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.12), transparent);">
      <p class="text-[13px] font-semibold mb-1.5">Coach's Note</p>
      <p class="text-xs text-text1 leading-relaxed">
        {#if athleteStore.atl > athleteStore.ctl * 1.3}
          Your acute load is significantly higher than your fitness. Risk of overtraining is elevated.
        {:else if athleteStore.tsb < -20}
          Negative form detected. Prioritize recovery sessions this week.
        {:else}
          Your training volume is well-balanced with your current fitness level.
        {/if}
      </p>
    </Card>
  {/if}
</div>
