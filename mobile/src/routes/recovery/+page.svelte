<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { onMount } from 'svelte';
  import { addDays, format, subDays } from 'date-fns';
  import { page } from '$app/stores';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state(format(new Date(), 'yyyy-MM-dd')); // YYYY-MM-DD
  let dayIndex = $state(6); // default to most recent day in window (right)

  const today = $derived(new Date());
  const todayStr = $derived(format(today, 'yyyy-MM-dd'));

  const clampedEndDay = $derived.by(() => {
    const d = endPickerValue ? new Date(endPickerValue + 'T00:00:00') : new Date();
    if (Number.isNaN(d.getTime())) return today;
    return d > today ? today : d;
  });

  const windowStart = $derived(subDays(clampedEndDay, 6));
  const windowEnd = $derived(clampedEndDay);
  const rangeLabel = $derived(`${format(windowStart, 'MMM d')} – ${format(windowEnd, 'MMM d, yyyy')}`);
  const canGoForward = $derived(format(windowEnd, 'yyyy-MM-dd') !== todayStr);

  const days = $derived.by(() => {
    // Build oldest→newest for display (today on the right).
    const asc = Array.from({ length: 7 }, (_, i) => {
      const d = addDays(windowStart, i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      const dow = format(d, 'EE');
      const dayLabel = dow === 'Thu' ? 'Th' : dow.charAt(0);
      
      return {
        date: dateStr,
        label: dateStr === todayStr ? 'Today' : format(d, 'MMM d'),
        day: dayLabel,
        score: b?.recovery_score || 0,
        hrv: b?.hrv_rmssd || 0,
        rhr: b?.resting_hr || 0,
        sleepScore: b?.sleep_score || 0,
        missing: !b || !b.recovery_score,
        data: b
      };
    });
    return asc;
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.readiness > 0);
  
  const score = $derived(d.score || (d?.date === todayStr ? athleteStore.readiness : 0));
  const scoreColor = $derived(score >= 67 ? '#00C8A8' : score >= 34 ? '#FFCB88' : '#F07178');
  const quality = $derived(score >= 67 ? 'Optimal' : score >= 34 ? 'Moderate' : 'Fatigued');

  const avg7d = $derived.by(() => {
    const vals = days.map((x) => Number(x.score)).filter((v) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  });

  // Allow deep-linking to a specific day, e.g. /recovery?day=2026-04-22
  let lastAppliedDay = $state<string | null>(null);
  onMount(() => {
    const unsub = page.subscribe(($p) => {
      const day = $p.url.searchParams.get('day');
      if (!day || day === lastAppliedDay) return;
      lastAppliedDay = day;
      endPickerValue = day;
      dayIndex = 6;
    });

    return unsub;
  });
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
          onclick={() => (endPickerValue = format(subDays(windowEnd, 7), 'yyyy-MM-dd'))}
        >
          ←
        </button>
        <div class="w-[150px]">
          <DatePicker
            id="recovery-end"
            bind:value={endPickerValue}
            max={todayStr}
            ariaLabel="Select end day"
            buttonClass="h-8 px-2 pr-2 rounded-md border border-border bg-glass text-[12px] text-text0"
            popoverClass=""
          />
        </div>
        <button
          type="button"
          class="h-8 px-2.5 rounded-md border border-border bg-glass text-text0 text-[12px]"
          aria-label="Jump to today"
          onclick={() => {
            endPickerValue = todayStr;
            dayIndex = 6;
          }}
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
            endPickerValue = format(addDays(windowEnd, 7), 'yyyy-MM-dd');
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
              <Tag color={scoreColor}>{score >= 67 ? 'OPTIMAL' : score >= 34 ? 'MODERATE' : 'FATIGUED'}</Tag>
            </div>
            <p class="text-xs text-text1 leading-relaxed">
              {score >= 67 ? 'Your nervous system is well-rested and primed for quality effort.' : 
               score >= 34 ? 'Moderate physiological state. Listen to your body during training.' : 
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

      <!-- 28-Day Trend -->
      <Card>
        <div class="flex justify-between items-center mb-3">
          <p class="text-[13px] font-semibold">Recovery trends</p>
          <span class="text-[10px] text-text2 font-mono">
            avg {avg7d === null ? '--' : `${avg7d}/100`} · {score}/100 current
          </span>
        </div>
        <div class="flex gap-2 items-end h-[50px] mb-1 px-1 pb-2">
          {#each days as day, i (day.date)}
            {@const c = day.score >= 67 ? '#00C8A8' : day.score >= 34 ? '#FFCB88' : '#F07178'}
            <button
              type="button"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer"
              onclick={() => (dayIndex = i)}
              aria-label={`Select ${day.label}: ${day.score}/100`}
            >
              <div
                class="w-full rounded-t-sm transition-all duration-300"
                style="background: {i === dayIndex ? c : c + '44'}; height: {Math.max(4, (day.score / 100) * 50)}px;"
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
          {score >= 67 ? 'Your recovery architecture looks balanced. Systemic fatigue is low.' : 
           score >= 34 ? 'Your autonomic system is recovering. Focus on maintaining parasympathetic tone.' : 
           'High systemic load detected. Prioritize high-quality sleep to accelerate repair.'}
        </p>
      </Card>
    {/if}

    <!-- Timeline -->
  {/if}
</div>
