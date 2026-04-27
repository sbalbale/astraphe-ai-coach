<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { format } from 'date-fns';
</script>

<div class="flex flex-col gap-3">
  <!-- Header (Visible on Desktop, as Mobile has layout header) -->
  <div class="hidden md:flex justify-between items-start">
    <div>
      <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">{format(new Date(), 'EEEE, MMM d')}</p>
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Good morning, {authStore.user?.user_metadata?.full_name || 'Athlete'}</h1>
    </div>
    <div class="flex items-center gap-2">
      <div class="w-2 h-2 rounded-full bg-teal shadow-[0_0_8px_var(--teal)]"></div>
      <span class="text-[11px] text-text1 font-mono">LIVE</span>
    </div>
  </div>

  <!-- Readiness Card -->
  <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.18) 0%, rgba(0,200,168,0.10) 100%); border-color: rgba(70,33,255,0.3);">
    <div class="flex items-center gap-4">
      <RadialProgress value={athleteStore.readiness} max={100} size={64} color="#4621FF" label={athleteStore.readiness.toString()} sub="RDY" />
      <div class="flex-1">
        <div class="flex items-center gap-2 mb-1">
          <span class="font-semibold text-[15px]">Readiness Score</span>
          <Tag color="var(--teal)">OPTIMAL</Tag>
        </div>
        <p class="text-xs text-text1 leading-relaxed">HRV +4pts · Sleep {athleteStore.sleep}h · Resting HR 52bpm</p>
        <p class="text-[11px] text-text2 mt-1">Good window for quality effort today</p>
      </div>
    </div>
  </Card>

  <!-- Metric Row -->
  <div class="grid grid-cols-3 gap-2.5">
    <Card style="padding: 12px 14px;">
      <MetricBadge label="CTL" value={athleteStore.ctl} unit="" color="var(--teal)" sub="Fitness" />
    </Card>
    <Card style="padding: 12px 14px;">
      <MetricBadge label="ATL" value={athleteStore.atl} unit="" color="var(--amber)" sub="Fatigue" />
    </Card>
    <Card style="padding: 12px 14px;">
      <MetricBadge label="TSB" value={athleteStore.tsb > 0 ? `+${athleteStore.tsb}` : athleteStore.tsb} unit="" color="#4621FF" sub="Form" />
    </Card>
  </div>

  <!-- Training Load Chart -->
  {#if athleteStore.metrics?.trainingLoadData}
    <Card>
      <div class="flex justify-between items-center mb-3">
        <span class="text-[13px] font-semibold">Training Load</span>
        <div class="flex gap-3">
          <span class="text-[10px] text-teal font-mono flex items-center gap-1">
            <span class="w-4 h-0.5 bg-teal inline-block rounded-[1px]"></span> CTL
          </span>
          <span class="text-[10px] text-blue font-mono flex items-center gap-1">
            <span class="w-2.5 h-2.5 bg-blue/40 inline-block rounded-sm"></span> ATL
          </span>
        </div>
      </div>
      <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={110} />
    </Card>
  {/if}

  <!-- HRV + Sleep -->
  <div class="grid grid-cols-2 gap-2.5">
    <Card>
      <span class="text-[9px] text-text2 block mb-2 font-mono uppercase tracking-[0.08em]">HRV Trend</span>
      <span class="text-[20px] font-bold text-teal">{athleteStore.hrv} <span class="text-[11px] text-text2 font-normal">ms</span></span>
      <span class="text-[10px] text-teal block mb-2">↑ +6 this week</span>
      {#if athleteStore.biometrics?.hrvData}
        <LineChart data={athleteStore.biometrics.hrvData} color="#00C8A8" height={48} />
      {/if}
    </Card>
    
    <Card>
      <span class="text-[9px] text-text2 block mb-2 font-mono uppercase tracking-[0.08em]">Sleep</span>
      <span class="text-[20px] font-bold text-amber">{athleteStore.sleep} <span class="text-[11px] text-text2 font-normal">hrs</span></span>
      <span class="text-[10px] text-text2 block mb-2">avg 7d · 94% quality</span>
      {#if athleteStore.biometrics?.sleepData}
        <LineChart data={athleteStore.biometrics.sleepData} color="#FFCB88" height={48} />
      {/if}
    </Card>
  </div>

  <!-- Recent Workouts -->
  {#if athleteStore.plan?.workouts}
    <Card>
      <div class="flex justify-between items-center mb-3">
        <span class="text-[13px] font-semibold">Recent Activity</span>
        <Tag color="var(--blue)">SYNCED</Tag>
      </div>
      <div class="flex flex-col gap-2.5">
        {#each athleteStore.plan.workouts.slice(0, 3) as w, i}
          <div class="flex items-center gap-3 py-2.5 {i < 2 ? 'border-b border-border' : ''}">
            <div class="w-9 h-9 rounded-xl shrink-0 flex items-center justify-center text-[15px]
              {w.type === 'Run' ? 'bg-blue-dim border border-[rgba(70,33,255,0.3)]' : 
               w.type === 'Bike' ? 'bg-teal-dim border border-[rgba(0,200,168,0.3)]' : 
               'bg-amber-dim border border-[rgba(255,203,136,0.3)]'}">
              {w.type === 'Run' ? '🏃' : w.type === 'Bike' ? '🚴' : '💪'}
            </div>
            <div class="flex-1">
              <p class="text-[13px] font-medium">{w.title}</p>
              <p class="text-[11px] text-text2">{w.date} · {w.duration}</p>
            </div>
            <div class="text-right">
              <p class="text-[13px] font-semibold {w.load > 75 ? 'text-red' : w.load > 55 ? 'text-amber' : 'text-teal'}">{w.load}</p>
              <p class="text-[9px] text-text2 font-mono">TSS</p>
            </div>
          </div>
        {/each}
      </div>
    </Card>
  {/if}
</div>
