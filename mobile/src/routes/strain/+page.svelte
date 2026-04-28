<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { format, subDays } from 'date-fns';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  let dayIndex = $state(0); // Default to today (index 0)

  const days = $derived.by(() => {
    // Today on the left (index 0)
    return Array.from({ length: 7 }, (_, i) => {
      const d = subDays(new Date(), i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      const history = athleteStore.metrics?.trainingLoadData?.find((m: any) => m.date === dateStr);

      return {
        date: dateStr,
        label: i === 0 ? 'Today' : format(d, 'MMM d'),
        day: format(d, 'EE').charAt(0),
        score: b?.day_strain ? Math.round((b.day_strain / 21) * 100) : 0,
        ctl: history?.ctl || athleteStore.ctl || 0,
        atl: history?.atl || athleteStore.atl || 0,
        tsb: history?.tsb || athleteStore.tsb || 0,
        missing: !b && !history,
        data: b
      };
    });
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.atl > 0);
  
  const score = $derived(d.score || 0);
  const scoreColor = $derived(score >= 80 ? '#F07178' : score >= 40 ? '#FFCB88' : '#00C8A8');
  const quality = $derived(score >= 80 ? 'High' : score >= 40 ? 'Moderate' : 'Light');
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Physical Load</p>
    <h1 class="text-[22px] font-bold tracking-tight">Strain</h1>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Strain Data" 
      message="Connect WHOOP or your training watch to analyze your physiological load."
    />
  {:else if !hasData}
    <EmptyState 
      title="Waiting for Activity" 
      message="We're waiting for your training data to compute your daily strain."
      icon="🔥"
    />
  {:else}
    <!-- Date selector -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each days as day, i}
        <Pill active={dayIndex === i} onclick={() => (dayIndex = i)}>
          {day.label}
        </Pill>
      {/each}
    </div>

    {#if d.missing}
      <Card style="border-style: dashed; opacity: 0.8;">
        <div class="flex flex-col items-center justify-center py-6 text-center">
          <span class="text-[32px] mb-2">🤷‍♂️</span>
          <p class="text-[14px] font-bold mb-1">No strain data for {d.date}</p>
          <p class="text-[11px] text-text2 max-w-[200px]">
            We couldn't find any activity or biometric records for this day.
          </p>
        </div>
      </Card>
    {:else}
      <!-- Hero Card (Sleep Page Style) -->
      <Card style="background: var(--glass); border-color: var(--border);">
        <div class="flex items-center gap-5 py-1">
          <RadialProgress 
            value={score} 
            max={100} 
            size={72} 
            color={scoreColor} 
            label={score.toString()} 
            sub="STRAIN" 
          />
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-[18px] font-bold text-text0">{quality}</span>
              <Tag color={scoreColor}>{score >= 80 ? 'HIGH' : score >= 40 ? 'PRODUCTIVE' : 'BASE'}</Tag>
            </div>
            <p class="text-xs text-text1 leading-relaxed">
              {score >= 80 ? 'Your training volume is significantly higher than your baseline.' : 
               score >= 40 ? 'Productive stress detected. You are building fitness efficiently.' : 
               'Light recovery day. Focus on maintaining aerobic foundation.'}
            </p>
          </div>
        </div>
      </Card>

      <!-- Metrics Grid -->
      <div class="grid grid-cols-3 gap-2">
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">Fatigue</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{Math.round(d.atl)}</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">ATL</span>
          </div>
        </Card>
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">Fitness</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{Math.round(d.ctl)}</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">CTL</span>
          </div>
        </Card>
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">Form</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{Math.round(d.tsb)}</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">TSB</span>
          </div>
        </Card>
      </div>

      <!-- Analysis Card -->
      <Card style="background: var(--glass2); border-color: transparent;">
        <p class="text-[13px] font-semibold mb-1">Strain Analysis</p>
        <p class="text-[12px] text-text2 leading-relaxed italic">
          {d.tsb < -20 ? 'Your training form is highly negative. Prioritize active recovery sessions.' : 
           d.tsb > 10 ? 'Your body is fresh and primed for a high-intensity block. CTL is stable.' : 
           'Your training volume is well-balanced with your current fitness level.'}
        </p>
      </Card>
    {/if}

    <!-- Timeline -->
    <Card>
      <p class="text-[13px] font-semibold mb-3">7-Day Trend</p>
      <div class="flex gap-2 items-end h-[50px] mb-1 px-1">
        {#each [...days].reverse() as day, i}
          {@const actualIdx = 6 - i}
          {@const c = day.score >= 80 ? '#F07178' : day.score >= 40 ? '#FFCB88' : '#00C8A8'}
          <div class="flex-1 flex flex-col items-center gap-1 cursor-pointer" onclick={() => dayIndex = actualIdx}>
            <div class="w-full rounded-t-sm transition-all duration-300" 
                 style="background: {actualIdx === dayIndex ? c : c + '44'}; height: {Math.max(4, (day.score / 100) * 50)}px;"></div>
            <span class="text-[9px] font-mono {actualIdx === dayIndex ? 'text-text0' : 'text-text2'}">{day.day}</span>
          </div>
        {/each}
      </div>
    </Card>
  {/if}
</div>
