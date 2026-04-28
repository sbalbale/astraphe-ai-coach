<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import FormDateInput from '$lib/components/FormDateInput.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { addDays, format, subDays } from 'date-fns';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  // Rolling 7-day window (cannot go into the future).
  let selectedEndDay = $state(new Date()); // end-of-window
  let dayIndex = $state(0); // default to most recent day in window (left)

  const today = $derived(new Date());
  const todayStr = $derived(format(today, 'yyyy-MM-dd'));

  const clampedEndDay = $derived.by(() => {
    const d = selectedEndDay instanceof Date ? selectedEndDay : new Date(selectedEndDay);
    if (Number.isNaN(d.getTime())) return new Date();
    return d > today ? today : d;
  });

  const windowStart = $derived(subDays(clampedEndDay, 6));
  const windowEnd = $derived(clampedEndDay);
  const rangeLabel = $derived(`${format(windowStart, 'MMM d')} – ${format(windowEnd, 'MMM d, yyyy')}`);
  let endPickerValue = $state('');
  const canGoForward = $derived(format(windowEnd, 'yyyy-MM-dd') !== todayStr);

  $effect(() => {
    endPickerValue = format(windowEnd, 'yyyy-MM-dd');
  });

  $effect(() => {
    if (endPickerValue) selectedEndDay = new Date(endPickerValue);
  });

  const days = $derived.by(() => {
    return Array.from({ length: 7 }, (_, i) => {
      // Most recent day on the left (index 0)
      const d = subDays(windowEnd, i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      
      return {
        date: dateStr,
        label: dateStr === todayStr ? 'Today' : format(d, 'MMM d'),
        day: format(d, 'EE').charAt(0),
        score: b?.astrape_recovery_score || b?.recovery_score || 0,
        hrv: b?.hrv_rmssd || 0,
        rhr: b?.resting_hr || 0,
        sleepScore: b?.astrape_sleep_score || b?.sleep_score || 0,
        missing: !b || !b.recovery_score,
        data: b
      };
    });
  });

  $effect(() => {
    // Keep selection clamped to [0..6] and default to latest day in the window.
    dayIndex = Math.max(0, Math.min(6, dayIndex ?? 0));
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.readiness > 0);
  
  const score = $derived(d.score || (d?.date === todayStr ? athleteStore.readiness : 0));
  const scoreColor = $derived(score >= 75 ? '#00C8A8' : score >= 50 ? '#FFCB88' : '#F07178');
  const quality = $derived(score >= 75 ? 'Optimal' : score >= 50 ? 'Moderate' : 'Fatigued');
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Daily Readiness</p>
    <h1 class="text-[22px] font-bold tracking-tight">Recovery</h1>
  </div>

  {#if !isConnected}
    <EmptyState 
      title="No Recovery Data" 
      message="Connect WHOOP, Garmin, or Apple Health to see your recovery analysis."
    />
  {:else if !hasData}
    <EmptyState 
      title="Waiting for Sync" 
      message="We're waiting for your biometric data to compute your recovery score."
      icon="⏳"
    />
  {:else}
    <!-- 7-day window selector -->
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          class="h-8 w-8 rounded-md border border-border bg-glass text-text0"
          aria-label="Previous 7 days"
          onclick={() => (selectedEndDay = subDays(windowEnd, 7))}
        >
          ←
        </button>
        <div class="w-[150px]">
          <FormDateInput
            id="recovery-end"
            type="date"
            bind:value={endPickerValue}
            max={todayStr}
            ariaLabel="Select end day"
            inputClass="h-8 px-2 pr-9 rounded-md border border-border bg-glass text-[12px] text-text0"
          />
        </div>
        <button
          type="button"
          class="h-8 px-2.5 rounded-md border border-border bg-glass text-text0 text-[12px]"
          aria-label="Jump to today"
          onclick={() => (selectedEndDay = new Date())}
        >
          Today
        </button>
        <button
          type="button"
          class="h-8 w-8 rounded-md border border-border bg-glass text-text0"
          aria-label="Next 7 days"
          disabled={!canGoForward}
          style={!canGoForward ? 'opacity: 0.4; cursor: not-allowed;' : ''}
          onclick={() => {
            if (!canGoForward) return;
            selectedEndDay = addDays(windowEnd, 7);
          }}
        >
          →
        </button>
      </div>
      <div class="text-[11px] text-text2 font-mono text-right">
        {rangeLabel}
      </div>
    </div>

    <!-- Date selector -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each days as day, i (day.date)}
        <Pill active={dayIndex === i} onclick={() => (dayIndex = i)}>
          {day.label}
        </Pill>
      {/each}
    </div>

    {#if d.missing}
      <Card style="border-style: dashed; opacity: 0.8;">
        <div class="flex flex-col items-center justify-center py-6 text-center">
          <span class="text-[32px] mb-2">🤷‍♂️</span>
          <p class="text-[14px] font-bold mb-1">No recovery data for {d.date}</p>
          <p class="text-[11px] text-text2 max-w-[200px]">
            We couldn't find any biometric records for this day. Make sure your device synced recently.
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
            sub="SCORE" 
          />
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-[18px] font-bold text-text0">{quality}</span>
              <Tag color={scoreColor}>{score >= 75 ? 'OPTIMAL' : 'RECOVERING'}</Tag>
            </div>
            <p class="text-xs text-text1 leading-relaxed">
              {score >= 75 ? 'Your nervous system is well-rested and primed for quality effort.' : 
               score >= 50 ? 'Moderate physiological state. Listen to your body during training.' : 
               'Significant fatigue detected. Prioritize sleep and active recovery today.'}
            </p>
          </div>
        </div>
      </Card>

      <!-- Metrics Grid -->
      <div class="grid grid-cols-3 gap-2">
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">HRV</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{d.hrv}</span>
              <span class="text-[10px] text-text2">ms</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">Avg</span>
          </div>
        </Card>
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">RHR</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{d.rhr}</span>
              <span class="text-[10px] text-text2">bpm</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">Avg</span>
          </div>
        </Card>
        <Card style="padding: 12px; height: 100%;">
          <div class="flex flex-col">
            <span class="text-[10px] text-text2 font-mono uppercase mb-1">Sleep</span>
            <div class="flex items-baseline gap-1">
              <span class="text-[18px] font-bold text-text0">{d.sleepScore}</span>
              <span class="text-[10px] text-text2">%</span>
            </div>
            <span class="text-[9px] text-text2 mt-1">Score</span>
          </div>
        </Card>
      </div>

      <!-- 7-Day Trend -->
      <Card>
        <p class="text-[13px] font-semibold mb-3">7-Day Trend</p>
        <div class="flex gap-2 items-end h-[50px] mb-1 px-1">
          {#each days as day, i (day.date)}
            {@const c = day.score >= 75 ? '#00C8A8' : day.score >= 50 ? '#FFCB88' : '#F07178'}
            {@const barColor = day.missing ? 'rgba(255,255,255,0.14)' : c}
            {@const barColorMuted = day.missing ? 'rgba(255,255,255,0.08)' : c + '44'}
            <button
              type="button"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer"
              aria-label={`Select ${day.label} recovery: ${day.score}`}
              onclick={() => (dayIndex = i)}
            >
              <div
                class="w-full rounded-t-sm transition-all duration-300"
                style="background: {i === dayIndex ? barColor : barColorMuted}; height: {day.missing ? 6 : Math.max(4, (day.score / 100) * 50)}px;"
              ></div>
              <span class="text-[9px] font-mono {i === dayIndex ? 'text-text0' : 'text-text2'}">{day.day}</span>
            </button>
          {/each}
        </div>
      </Card>

      <!-- Analysis Card -->
      <Card style="background: var(--glass2); border-color: transparent;">
        <p class="text-[13px] font-semibold mb-1">Recovery Analysis</p>
        <p class="text-[12px] text-text2 leading-relaxed italic">
          {score >= 75 ? 'Your recovery architecture looks balanced. Systemic fatigue is low.' : 
           score >= 50 ? 'Your autonomic system is recovering. Focus on maintaining parasympathetic tone.' : 
           'High systemic load detected. Prioritize high-quality sleep to accelerate repair.'}
        </p>
      </Card>
    {/if}

    <!-- Timeline -->
  {/if}
</div>
