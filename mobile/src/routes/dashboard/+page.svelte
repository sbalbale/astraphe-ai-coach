<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';
  import { format } from 'date-fns';

  const hasData = $derived(athleteStore.workouts?.length > 0 || athleteStore.readiness > 0);
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
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
      <span class="text-[11px] text-text1 font-mono">{isConnected ? 'LIVE' : 'OFFLINE'}</span>
    </div>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Apps Connected" 
      message="Link Garmin, WHOOP, or Apple Health to see your training metrics and AI coaching."
      actionLabel="Connect Now"
      icon="⚡"
    />
  {:else if !hasData}
    <EmptyState 
      title="Waiting for Data" 
      message="Your apps are connected. We're waiting for your first activity or biometric sync."
      actionLabel="Check Sync Status"
      icon="⏳"
    />
  {:else}
    <!-- Readiness Card -->
    <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.18) 0%, rgba(0,200,168,0.10) 100%); border-color: rgba(70,33,255,0.3);">
      <div class="flex items-center gap-4">
        <RadialProgress value={athleteStore.readiness} max={100} size={64} color="#4621FF" label={athleteStore.readiness.toString()} sub="RDY" />
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="font-semibold text-[15px]">Readiness Score</span>
            {#if athleteStore.readiness > 70}
              <Tag color="var(--teal)">OPTIMAL</Tag>
            {:else if athleteStore.readiness > 40}
              <Tag color="var(--amber)">MODERATE</Tag>
            {:else}
              <Tag color="var(--red)">RECOVERY</Tag>
            {/if}
          </div>
          <p class="text-xs text-text1 leading-relaxed">
            HRV {athleteStore.hrv}ms · Sleep {athleteStore.sleep}h
          </p>
          <p class="text-[11px] text-text2 mt-1">Data synced from your connected services.</p>
        </div>
      </div>
    </Card>

    <!-- Metric Row -->
    <div class="grid grid-cols-3 gap-2.5">
      <Card style="padding: 12px 14px;">
        <MetricBadge label="CTL" value={Math.round(athleteStore.ctl)} unit="" color="var(--teal)" sub="Fitness" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="ATL" value={Math.round(athleteStore.atl)} unit="" color="var(--amber)" sub="Fatigue" />
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="TSB" value={athleteStore.tsb > 0 ? `+${Math.round(athleteStore.tsb)}` : Math.round(athleteStore.tsb)} unit="" color="#4621FF" sub="Form" />
      </Card>
    </div>

    <!-- Training Load Chart -->
    {#if athleteStore.metrics?.trainingLoadData?.length > 0}
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
        {#if athleteStore.biometrics?.hrvData?.length > 1}
          <LineChart data={athleteStore.biometrics.hrvData} color="#00C8A8" height={48} />
        {:else}
          <div class="h-[48px] flex items-center justify-center text-[10px] text-text2 italic">Pending data...</div>
        {/if}
      </Card>
      
      <Card>
        <span class="text-[9px] text-text2 block mb-2 font-mono uppercase tracking-[0.08em]">Sleep</span>
        <span class="text-[20px] font-bold text-amber">{athleteStore.sleep} <span class="text-[11px] text-text2 font-normal">hrs</span></span>
        {#if athleteStore.biometrics?.sleepData?.length > 1}
          <LineChart data={athleteStore.biometrics.sleepData} color="#FFCB88" height={48} />
        {:else}
          <div class="h-[48px] flex items-center justify-center text-[10px] text-text2 italic">Pending data...</div>
        {/if}
      </Card>
    </div>

    <!-- Recent Activity -->
    {#if athleteStore.workouts?.length > 0}
      <Card>
        <div class="flex justify-between items-center mb-3">
          <span class="text-[13px] font-semibold">Recent Activity</span>
          <Tag color="var(--blue)">SYNCED</Tag>
        </div>
        <div class="flex flex-col gap-2.5">
          {#each athleteStore.workouts.slice(0, 3) as w, i}
            {@const type = w.sport?.toLowerCase()}
            <button
              type="button"
              class="text-left bg-transparent border-none p-0 cursor-pointer w-full"
              onclick={() => goto(`/training?workout_id=${encodeURIComponent(String(w.id))}`)}
              aria-label="View workout details"
            >
              <div class="flex items-center gap-3 py-2.5 {i < 2 ? 'border-b border-border' : ''}">
                <div class="w-9 h-9 rounded-xl shrink-0 flex items-center justify-center text-[15px]
                  {type === 'run' ? 'bg-blue-dim border border-[rgba(70,33,255,0.3)]' : 
                   type === 'bike' || type === 'cycling' ? 'bg-teal-dim border border-[rgba(0,200,168,0.3)]' : 
                   type === 'rowing' ? 'bg-amber-dim border border-[rgba(255,203,136,0.3)]' :
                   'bg-glass border border-border'}">
                  {type === 'run' ? '🏃' : (type === 'bike' || type === 'cycling') ? '🚴' : type === 'rowing' ? '🚣' : '💪'}
                </div>
                <div class="flex-1">
                  <p class="text-[13px] font-medium">{w.title || (w.sport?.toUpperCase() + ' Session')}</p>
                  <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(w.duration_secs / 60)} min</p>
                </div>
                <div class="text-right">
                  <p class="text-[13px] font-semibold {w.tss > 75 ? 'text-red' : w.tss > 55 ? 'text-amber' : 'text-teal'}">{Math.round(w.tss || 0)}</p>
                  <p class="text-[9px] text-text2 font-mono">TSS</p>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </Card>
    {/if}
  {/if}
</div>
