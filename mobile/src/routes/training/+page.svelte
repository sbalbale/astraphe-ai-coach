<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import DonutChart from '$lib/components/charts/DonutChart.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { format } from 'date-fns';

  let metric = $state('load');
  const tabs = ['load', 'history']; // Simplified tabs for now as pace/zones need complex processing
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  const hasWorkouts = $derived(athleteStore.workouts?.length > 0);

  let selectedWorkout = $state<any>(null);

  function getWorkoutIcon(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run') return '🏃';
    if (t === 'bike' || t === 'cycling') return '🚴';
    if (t === 'rowing') return '🚣';
    if (t === 'swim') return '🏊';
    if (t === 'strength') return '💪';
    return '🏋️';
  }

  function getWorkoutColor(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run') return 'var(--blue)';
    if (t === 'bike' || t === 'cycling') return 'var(--teal)';
    if (t === 'rowing') return 'var(--amber)';
    return 'var(--text2)';
  }

  function getWorkoutBg(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run') return 'bg-blue-dim border-blue-glow';
    if (t === 'bike' || t === 'cycling') return 'bg-teal-dim border-[rgba(0,200,168,0.3)]';
    if (t === 'rowing') return 'bg-amber-dim border-[rgba(255,203,136,0.3)]';
    return 'bg-glass border-border';
  }

  const weeklyTss = $derived(athleteStore.workouts?.slice(0, 7).reduce((acc, w) => acc + (w.tss || 0), 0) || 0);
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Performance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Analysis</h1>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Training Data" 
      message="Connect your training apps to analyze your performance trends and history."
    />
  {:else if !hasWorkouts}
    <EmptyState 
      title="Waiting for Workouts" 
      message="We're waiting for your training history to sync from your connected services."
      icon="⏳"
    />
  {:else}
    <!-- Metric Tabs -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each tabs as tab}
        <Pill active={metric === tab} onclick={() => { metric = tab; selectedWorkout = null; }}>
          {tab.charAt(0).toUpperCase() + tab.slice(1)}
        </Pill>
      {/each}
    </div>

    {#if metric === 'load'}
      <div class="grid grid-cols-2 gap-2.5">
        <Card>
          <MetricBadge label="Fitness (CTL)" value={Math.round(athleteStore.ctl)} color="var(--teal)" sub="Long-term load" />
        </Card>
        <Card>
          <MetricBadge label="Fatigue (ATL)" value={Math.round(athleteStore.atl)} color="var(--amber)" sub="Short-term load" />
        </Card>
        <Card>
          <MetricBadge label="Form (TSB)" value={athleteStore.tsb > 0 ? `+${Math.round(athleteStore.tsb)}` : Math.round(athleteStore.tsb)} color="#4621FF" sub="Training balance" />
        </Card>
        <Card>
          <MetricBadge label="Weekly TSS" value={Math.round(weeklyTss)} color="var(--red)" sub="Last 7 days" />
        </Card>
      </div>
      
      {#if athleteStore.metrics?.trainingLoadData?.length > 0}
        <Card>
          <p class="text-[13px] font-semibold mb-3">Training Load Trend</p>
          <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
        </Card>
      {/if}
      
      <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
        <p class="text-[13px] font-semibold mb-1.5">Load Insight</p>
        <p class="text-xs text-text1 leading-relaxed">
          {#if athleteStore.tsb > 10}
            You have significant freshnesh (TSB +{Math.round(athleteStore.tsb)}). Excellent time for a peak performance or hard test.
          {:else if athleteStore.tsb < -20}
            High fatigue detected. Consider a deload week to allow CTL to catch up to ATL safely.
          {:else}
            Your training load is stable. Continue with your planned progression.
          {/if}
        </p>
      </Card>
    {/if}

    {#if metric === 'history'}
      {#if selectedWorkout}
        <!-- Detailed Workout View -->
        <button class="mb-2 text-xs text-blue flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer" onclick={() => selectedWorkout = null}>
          ← Back to list
        </button>
        
        <Card>
          <div class="flex items-center gap-4 mb-4">
            <div class="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl {getWorkoutBg(selectedWorkout.sport)}">
              {getWorkoutIcon(selectedWorkout.sport)}
            </div>
            <div class="flex-1">
              <h2 class="text-lg font-bold leading-tight">{selectedWorkout.title || (selectedWorkout.sport.toUpperCase() + ' Session')}</h2>
              <p class="text-xs text-text2">{format(new Date(selectedWorkout.started_at), 'EEEE, MMM d · h:mm a')}</p>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold" style="color: {getWorkoutColor(selectedWorkout.sport)}">{Math.round(selectedWorkout.tss || 0)}</p>
              <p class="text-[10px] text-text2 font-mono">TSS</p>
            </div>
          </div>

          <div class="grid grid-cols-3 gap-2 mb-5">
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Duration</p>
              <p class="text-sm font-bold">{Math.floor(selectedWorkout.duration_secs / 60)}m</p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Distance</p>
              <p class="text-sm font-bold">{selectedWorkout.distance_m ? (selectedWorkout.distance_m / 1000).toFixed(2) + 'km' : '--'}</p>
            </div>
            <div class="bg-glass2 p-2.5 rounded-xl border border-border">
              <p class="text-[9px] text-text2 font-mono uppercase mb-1">Avg HR</p>
              <p class="text-sm font-bold">{selectedWorkout.avg_hr || '--'} <span class="text-[10px] font-normal opacity-60">bpm</span></p>
            </div>
          </div>

          <div class="p-3 bg-blue-dim rounded-xl border-l-2 border-blue">
            <p class="text-[11px] font-semibold text-blue mb-1">Analysis</p>
            <p class="text-[11px] text-text1 leading-relaxed">
              This session contributed {Math.round(selectedWorkout.tss || 0)} points to your acute load. {selectedWorkout.tss > 80 ? 'Ensure proper recovery tonight.' : 'Good aerobic contribution.'}
            </p>
          </div>
        </Card>
      {:else}
        <div class="flex flex-col gap-2.5">
          {#each athleteStore.workouts as w}
            <button class="text-left bg-transparent border-none p-0 cursor-pointer w-full" onclick={() => selectedWorkout = w}>
              <Card style="padding: 12px 14px;">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center text-[18px] {getWorkoutBg(w.sport)}">
                    {getWorkoutIcon(w.sport)}
                  </div>
                  <div class="flex-1">
                    <p class="text-[13px] font-semibold">{w.title || (w.sport.charAt(0).toUpperCase() + w.sport.slice(1) + ' Session')}</p>
                    <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(w.duration_secs / 60)} min</p>
                  </div>
                  <div class="text-right">
                    <p class="text-[16px] font-bold" style="color: {getWorkoutColor(w.sport)}">{Math.round(w.tss || 0)}</p>
                    <p class="text-[9px] text-text2 font-mono">TSS</p>
                  </div>
                </div>
              </Card>
            </button>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>
