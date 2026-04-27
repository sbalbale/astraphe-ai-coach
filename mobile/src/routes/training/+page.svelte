<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import DonutChart from '$lib/components/charts/DonutChart.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { format } from 'date-fns';

  let metric = $state('load');
  const tabs = ['load', 'pace', 'zones', 'history'];

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
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Performance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Analysis</h1>
  </div>

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
      <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.12), transparent);">
        <MetricBadge label="Fitness (CTL)" value={athleteStore.ctl} color="var(--teal)" sub="↑ 7 pts / 4 weeks" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(255,203,136,0.12), transparent);">
        <MetricBadge label="Fatigue (ATL)" value={athleteStore.atl} color="var(--amber)" sub="↓ 57 pts from peak" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
        <MetricBadge label="Form (TSB)" value={athleteStore.tsb > 0 ? `+${athleteStore.tsb}` : athleteStore.tsb} color="#4621FF" sub="Optimal race window" />
      </Card>
      <Card style="background: linear-gradient(135deg, rgba(240,113,120,0.12), transparent);">
        <MetricBadge label="Weekly TSS" value={389} color="var(--red)" sub="↑ 12% vs last week" />
      </Card>
    </div>
    
    {#if athleteStore.metrics?.trainingLoadData}
      <Card>
        <p class="text-[13px] font-semibold mb-3">7-Day Load</p>
        <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={120} />
      </Card>
    {/if}
    
    <Card>
      <p class="text-[13px] font-semibold mb-1">AI Insight</p>
      <p class="text-xs text-text1 leading-relaxed p-2.5 bg-blue-dim rounded-xl border-l-2 border-blue">
        Your CTL trajectory is ideal — 7pt gain over 4 weeks. TSB of +{athleteStore.tsb} means you're primed. I recommend a hard effort this week before resuming your build block.
      </p>
    </Card>
  {/if}

  {#if metric === 'pace'}
    {#if athleteStore.metrics?.paceData}
      <Card>
        <p class="text-[13px] font-semibold mb-1">Last Long Run — Pace/km</p>
        <p class="text-[11px] text-text2 mb-3">Apr 24 · 10km · avg 5:38/km</p>
        <LineChart data={athleteStore.metrics.paceData} yKey="pace" color="#4621FF" height={100} labels={athleteStore.metrics.paceData.map((d: any) => d.dist > 0 ? d.dist+'km' : '')} />
      </Card>
    {/if}
    <div class="grid grid-cols-3 gap-2.5">
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Avg Pace" value="5:38" unit="/km" color="#4621FF" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Best km" value="5:12" unit="/km" color="var(--teal)" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="Avg HR" value="148" unit="bpm" color="var(--red)" />
      </Card>
    </div>
    <Card>
      <p class="text-[13px] font-semibold mb-1">Running Economy</p>
      <p class="text-xs text-text1 leading-relaxed p-2.5 bg-teal-dim rounded-xl border-l-2 border-teal">
        Pace/HR ratio improved 3.2% vs last month. Your aerobic efficiency is trending up — a strong indicator of fitness adaptation.
      </p>
    </Card>
  {/if}

  {#if metric === 'zones'}
    {#if athleteStore.metrics?.zoneData}
      <Card>
        <div class="flex gap-5 items-center">
          <DonutChart data={athleteStore.metrics.zoneData} size={100} />
          <div class="flex-1 flex flex-col gap-2">
            {#each athleteStore.metrics.zoneData as z}
              <div class="flex items-center gap-2">
                <div class="w-2 h-2 rounded-full shrink-0" style="background: {z.color}"></div>
                <span class="text-xs text-text1 flex-1">{z.zone}</span>
                <div class="flex-[2] h-1 bg-glass2 rounded overflow-hidden">
                  <div class="h-full rounded" style="width: {z.pct}%; background: {z.color}"></div>
                </div>
                <span class="text-[11px] font-mono w-8 text-right" style="color: {z.color}">{z.pct}%</span>
              </div>
            {/each}
          </div>
        </div>
      </Card>
    {/if}
    <Card style="background: linear-gradient(135deg, rgba(0,200,168,0.1), transparent);">
      <p class="text-[13px] font-semibold mb-2">Distribution Score</p>
      <div class="flex items-center gap-3">
        <RadialProgress value={84} max={100} size={56} color="var(--teal)" label="84" />
        <div>
          <p class="text-[14px] font-semibold text-teal">Excellent</p>
          <p class="text-xs text-text1 leading-relaxed">Polarized 80/20 model. Zone 2 at 42% — on point. Reduce Z3 slightly next week.</p>
        </div>
      </div>
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
            <p class="text-2xl font-bold" style="color: {getWorkoutColor(selectedWorkout.sport)}">{selectedWorkout.tss || 0}</p>
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

        <!-- Effort Graph (Placeholder for detailed time-series) -->
        <p class="text-xs font-semibold mb-2">Heart Rate Effort</p>
        <div class="h-24 bg-glass rounded-xl border border-border mb-4 relative overflow-hidden">
           <!-- Simulation of a heart rate graph -->
           <div class="absolute inset-0 opacity-20 pointer-events-none">
             <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
               <path d="M0 80 L10 75 L20 60 L30 65 L40 40 L50 45 L60 20 L70 30 L80 15 L90 25 L100 10 L100 100 L0 100 Z" fill={getWorkoutColor(selectedWorkout.sport)} />
             </svg>
           </div>
           <div class="absolute inset-0 flex items-center justify-center">
             <p class="text-[10px] text-text2 font-mono">Detailed Analysis via Garmin/WHOOP</p>
           </div>
        </div>

        <div class="p-3 bg-blue-dim rounded-xl border-l-2 border-blue">
          <p class="text-[11px] font-semibold text-blue mb-1">ASTRAPE Insight</p>
          <p class="text-[11px] text-text1 leading-relaxed">
            {selectedWorkout.tss > 80 ? 'High intensity session. Your ATL spiked significantly. Focus on Z1 recovery tomorrow.' : 'Optimal load session. HR remained stable across intervals, showing good aerobic control.'}
          </p>
        </div>
      </Card>
    {:else}
      <div class="flex flex-col gap-2.5">
        {#if athleteStore.workouts?.length > 0}
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
                    <p class="text-[16px] font-bold" style="color: {getWorkoutColor(w.sport)}">{w.tss || 0}</p>
                    <p class="text-[9px] text-text2 font-mono">TSS</p>
                  </div>
                </div>
              </Card>
            </button>
          {/each}
        {:else}
          <p class="text-center text-text2 py-10 text-sm">No workouts found.</p>
        {/if}
      </div>
    {/if}
  {/if}
</div>
