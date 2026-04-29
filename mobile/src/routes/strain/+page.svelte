<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { addDays, format, subDays } from 'date-fns';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state('');
  let dayIndex = $state(0); // most recent on the left
  const isoDate = (value: unknown) => (typeof value === 'string' ? value.slice(0, 10) : '');

  const today = $derived(new Date());
  const todayStr = $derived(format(today, 'yyyy-MM-dd'));

  $effect(() => {
    if (!endPickerValue) endPickerValue = todayStr;
  });

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
    return Array.from({ length: 7 }, (_, i) => {
      // Most recent day on the left (index 0)
      const d = subDays(windowEnd, i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      const history = athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === dateStr);
      const hasStrain = b?.strain_score !== null && b?.strain_score !== undefined;

      // Workout-derived strain proxy (preferred when strain_score isn't present).
      // We treat "strain" as "did you train today?" — if no workout, show 0 and no warning.
      const workoutsForDay = athleteStore.workouts?.filter((w: any) => isoDate(w?.started_at) === dateStr) || [];
      const hasWorkout = workoutsForDay.length > 0;
      const workoutStrainScore = Math.min(
        100,
        Math.round(
          workoutsForDay.reduce((acc: number, w: any) => {
            const s = Number(w?.strain_score);
            if (!Number.isNaN(s) && s > 0) return acc + s;
            const tss = Number(w?.tss);
            if (!Number.isNaN(tss) && tss > 0) return acc + (tss / 150) * 100;
            return acc;
          }, 0),
        ),
      );
      const computedScore = hasStrain ? Math.round(b.strain_score) : hasWorkout ? workoutStrainScore : 0;

      return {
        date: dateStr,
        label: dateStr === todayStr ? 'Today' : format(d, 'MMM d'),
        day: format(d, 'EE').charAt(0),
        score: computedScore,
        ctl: history?.ctl || athleteStore.ctl || 0,
        atl: history?.atl || athleteStore.atl || 0,
        tsb: history?.tsb || athleteStore.tsb || 0,
        workouts: workoutsForDay,
        // Only show "no strain data" when a workout exists but we still can't compute strain.
        missing: hasWorkout && !hasStrain && computedScore === 0,
        data: b
      };
    });
  });

  $effect(() => {
    dayIndex = Math.max(0, Math.min(6, dayIndex ?? 0));
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.atl > 0);
  
  const score = $derived(d.score || 0);
  const scoreColor = $derived(score >= 80 ? '#F07178' : score >= 40 ? '#FFCB88' : '#00C8A8');
  const quality = $derived(score >= 80 ? 'High' : score >= 40 ? 'Moderate' : 'Light');

  function getWorkoutIcon(type: string) {
    const t = type?.toLowerCase();
    if (t === 'run') return '🏃';
    if (t === 'bike' || t === 'cycling') return '🚴';
    if (t === 'rowing') return '🚣';
    if (t === 'swim') return '🏊';
    if (t === 'strength' || t === 'strength_training' || t === 'gym') return '💪';
    return '🏋️';
  }

  function getWorkoutLabel(type: string) {
    const t = type?.toLowerCase();
    if (t === 'strength_training' || t === 'strength' || t === 'gym') return 'Strength';
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Workout';
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

  function getDurationSecs(w: any): number {
    const direct = w?.duration_secs ?? w?.duration_seconds;
    if (Number.isFinite(direct)) return Math.max(0, Math.floor(Number(direct)));
    return 0;
  }
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
            id="strain-end"
            bind:value={endPickerValue}
            max={todayStr}
            ariaLabel="Select end day"
            buttonClass="h-8 px-2 pr-2 rounded-md border border-border bg-glass text-[12px] text-text0"
          />
        </div>
        <button
          type="button"
          class="h-8 px-2.5 rounded-md border border-border bg-glass text-text0 text-[12px]"
          aria-label="Jump to today"
          onclick={() => {
            endPickerValue = todayStr;
            dayIndex = 0;
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

      <!-- Timeline -->
      <Card>
        <p class="text-[13px] font-semibold mb-3">7-Day Trend</p>
        <div class="flex gap-2 items-end h-[50px] mb-1 px-1">
          {#each days as day, i (day.date)}
            {@const c = day.score >= 80 ? '#F07178' : day.score >= 40 ? '#FFCB88' : '#00C8A8'}
            <button
              type="button"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer"
              onclick={() => (dayIndex = i)}
            >
              <div class="w-full rounded-t-sm transition-all duration-300" 
                   style="background: {i === dayIndex ? c : c + '44'}; height: {Math.max(4, (day.score / 100) * 50)}px;"></div>
              <span class="text-[9px] font-mono {i === dayIndex ? 'text-text0' : 'text-text2'}">{day.day}</span>
            </button>
          {/each}
        </div>
      </Card>

      {#if d.workouts && d.workouts.length > 0}
        <div>
          <p class="text-[11px] text-text2 font-mono uppercase tracking-[0.05em] mb-2 px-1">Contributing Activities</p>
          <div class="flex flex-col gap-2">
            {#each d.workouts as w (w.id || w.started_at)}
              <Card style="padding: 12px 14px;">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center text-[18px] {getWorkoutBg(w.sport)}">
                    {getWorkoutIcon(w.sport)}
                  </div>
                  <div class="flex-1">
                    <p class="text-[13px] font-semibold">{w.title || (getWorkoutLabel(w.sport) + ' Session')}</p>
                    <p class="text-[11px] text-text2">
                      {Math.floor(getDurationSecs(w) / 60)} min · {format(new Date(w.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'HH:mm' : 'h:mm a')}
                    </p>
                  </div>
                  <div class="text-right">
                    <p class="text-[16px] font-bold" style="color: {getWorkoutColor(w.sport)}">
                      {Math.round(w.strain_score || w.tss || 0)}
                    </p>
                    <p class="text-[9px] text-text2 font-mono">{w.strain_score ? 'STRAIN' : 'TSS'}</p>
                  </div>
                </div>
              </Card>
            {/each}
          </div>
        </div>
      {/if}

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
  {/if}
</div>
