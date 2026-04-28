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
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { page } from '$app/stores';
  import { addDays, endOfWeek, format, startOfWeek } from 'date-fns';

  let metric = $state('load');
  const tabs = ['load', 'history']; // Simplified tabs for now as pace/zones need complex processing
  // Avoid UI flicker: `syncStatus` can be briefly null/undefined even when workouts are loaded.
  // Only show "No Training Data" once we know initial load is done and we truly have no workouts.
  const hasWorkouts = $derived(athleteStore.workouts?.length > 0);
  const isConnected = $derived(
    athleteStore.syncStatus
      ? Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected)
      : true
  );
  const showNoTrainingData = $derived(athleteStore.initialLoadDone && !athleteStore.loading && !isConnected && !hasWorkouts);

  let selectedWorkout = $state<any>(null);

  const zoneColors = ['#4621FF', '#00C8A8', '#FFCB88', '#F07178', '#FF4791'];

  // Week selector (History tab)
  // Source of truth is the picked day (YYYY-MM-DD). We derive the Monday week start from it.
  let weekPickerValue = $state('');
  let appliedWorkoutIdFromUrl = $state(false);

  function parseDateInputLocal(value: string): Date {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!m) return new Date(value);
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    // Use local time to avoid timezone shifting when parsing YYYY-MM-DD
    return new Date(y, mo - 1, d, 12, 0, 0, 0);
  }

  $effect(() => {
    if (!weekPickerValue) weekPickerValue = format(new Date(), 'yyyy-MM-dd');
  });

  const selectedWeekStart = $derived.by(() => startOfWeek(parseDateInputLocal(weekPickerValue), { weekStartsOn: 1 }));
  const selectedWeekEnd = $derived(endOfWeek(selectedWeekStart, { weekStartsOn: 1 }));
  function jumpToCurrentWeek() {
    weekPickerValue = format(new Date(), 'yyyy-MM-dd');
  }

  const workoutIdFromUrl = $derived($page.url.searchParams.get('workout_id'));
  $effect(() => {
    if (appliedWorkoutIdFromUrl) return;
    if (!workoutIdFromUrl) return;
    if (!hasWorkouts) return;

    const match = (athleteStore.workouts || []).find((w) => String(w?.id) === String(workoutIdFromUrl));
    if (!match) return;

    metric = 'history';
    weekPickerValue = format(new Date(match.started_at), 'yyyy-MM-dd');
    selectedWorkout = match;
    appliedWorkoutIdFromUrl = true;
  });

  const weekWorkouts = $derived.by(() => {
    const start = selectedWeekStart.getTime();
    const end = selectedWeekEnd.getTime();
    return (athleteStore.workouts || []).filter((w) => {
      const t = w?.started_at ? new Date(w.started_at).getTime() : NaN;
      return Number.isFinite(t) && t >= start && t <= end;
    });
  });

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

  const weeklyTss = $derived(athleteStore.workouts?.slice(0, 7).reduce((acc, w) => acc + (w.tss || 0), 0) || 0);

  function getDurationSecs(w: any): number {
    const direct = w?.duration_secs ?? w?.duration_seconds;
    if (Number.isFinite(direct)) return Math.max(0, Math.floor(Number(direct)));

    const start = w?.started_at ? new Date(w.started_at) : null;
    const end = w?.ended_at ? new Date(w.ended_at) : null;
    if (!start || !end) return 0;
    const ms = end.getTime() - start.getTime();
    if (!Number.isFinite(ms)) return 0;
    return Math.max(0, Math.floor(ms / 1000));
  }

  function formatMMSS(totalSeconds: number): string {
    const s = Math.max(0, Math.floor(totalSeconds || 0));
    const m = Math.floor(s / 60);
    const ss = String(s % 60).padStart(2, '0');
    return `${m}:${ss}`;
  }

  function getHrZonePcts(w: any): Array<number | null> {
    const z1 = w?.hr_zone_1_pct ?? null;
    const z2 = w?.hr_zone_2_pct ?? null;
    const z3 = w?.hr_zone_3_pct ?? null;
    const z4 = w?.hr_zone_4_pct ?? null;
    const z5 = w?.hr_zone_5_pct ?? null;
    const z0 =
      w?.hr_zone_0_pct ?? (z1 == null ? null : Math.max(0, 100 - Number(z1 || 0) - Number(z2 || 0) - Number(z3 || 0) - Number(z4 || 0) - Number(z5 || 0)));

    return [
      z0,
      w?.hr_zone_1_pct ?? null,
      w?.hr_zone_2_pct ?? null,
      w?.hr_zone_3_pct ?? null,
      w?.hr_zone_4_pct ?? null,
      w?.hr_zone_5_pct ?? null
    ].map((v) => (v == null ? null : Number(v)));
  }

  function getHrZonePctsTopDown(w: any): Array<number | null> {
    // Display order: Z5 (top) -> Z0 (bottom)
    return getHrZonePcts(w).slice().reverse();
  }

  function hasAnyHrZone(w: any): boolean {
    return getHrZonePcts(w).some((v) => v != null);
  }

  async function deleteSelectedWorkout() {
    if (!selectedWorkout?.id) return;
    if (!confirm('Delete this workout?')) return;
    try {
      await athleteStore.deleteWorkout(selectedWorkout.id);
      selectedWorkout = null;
    } catch (e) {
      console.error(e);
      alert('Failed to delete workout');
    }
  }
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Performance</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Analysis</h1>
  </div>

  {#if showNoTrainingData}
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
      {#each tabs as tab (tab)}
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
        <div class="mb-2 flex items-center justify-between gap-2">
          <button
            class="text-xs text-blue flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer"
            onclick={() => (selectedWorkout = null)}
          >
            ← Back to list
          </button>

          <button
            class="text-xs text-red bg-transparent border-none p-0 cursor-pointer"
            onclick={deleteSelectedWorkout}
          >
            Delete
          </button>
        </div>
        
        <Card>
          <div class="flex items-center gap-4 mb-4">
            <div class="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl {getWorkoutBg(selectedWorkout.sport)}">
              {getWorkoutIcon(selectedWorkout.sport)}
            </div>
            <div class="flex-1">
              <h2 class="text-lg font-bold leading-tight">{selectedWorkout.title || (getWorkoutLabel(selectedWorkout.sport) + ' Session')}</h2>
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
              <p class="text-sm font-bold">{Math.floor(getDurationSecs(selectedWorkout) / 60)}m</p>
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

          <div class="mb-5 bg-glass2 p-3 rounded-xl border border-border">
            <p class="text-[11px] font-semibold mb-2">Heart-rate zones</p>

            {#if hasAnyHrZone(selectedWorkout)}
              <div class="flex flex-col gap-2">
                {#each getHrZonePctsTopDown(selectedWorkout) as pct, topIdx (topIdx)}
                  {@const zone = 5 - topIdx}
                  {@const color = zoneColors[zone - 1]}
                  <div class="flex items-center gap-3">
                    <div class="w-9 shrink-0 flex items-center gap-2">
                      <span class="w-2 h-2 rounded-full shrink-0" style="background: {color};"></span>
                      <p class="text-[11px] text-text1 font-mono uppercase">Z{zone}</p>
                    </div>

                    <div class="flex-1">
                      <div class="h-2.5 rounded-full bg-glass border border-border overflow-hidden">
                        <div
                          class="h-full rounded-full"
                          style="width: {pct == null ? 0 : Math.max(0, Math.min(100, pct))}%; background: {color};"
                        ></div>
                      </div>
                    </div>

                    <div class="w-[92px] shrink-0 text-right">
                      <p class="text-[11px] text-text2 font-mono">{pct == null ? '--' : `${Math.round(pct)}%`}</p>
                      <p class="text-[11px] text-text1 font-semibold tabular-nums">
                        {pct == null ? '--' : formatMMSS((getDurationSecs(selectedWorkout) * pct) / 100)}
                      </p>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-[11px] text-text2">No zone data for this workout</p>
            {/if}
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
          <!-- Week selector -->
          <Card style="padding: 12px 14px;">
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.08em]">Week</p>
                <p class="text-[13px] font-semibold truncate">
                  {format(selectedWeekStart, 'MMM d')} – {format(selectedWeekEnd, 'MMM d')}
                </p>
              </div>

              <div class="flex items-center gap-2 shrink-0">
                <button
                  class="px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, -7), 'yyyy-MM-dd'))}
                  aria-label="Previous week"
                >
                  ←
                </button>

                <div class="w-[160px]">
                  <DatePicker
                    id="training-history-week"
                    bind:value={weekPickerValue}
                    ariaLabel="Select week"
                    buttonClass="px-2 py-1 pr-2 rounded-lg border border-border bg-glass2 text-[11px] text-text1"
                  />
                </div>

                <button
                  class="px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={jumpToCurrentWeek}
                  aria-label="Jump to current week"
                >
                  Today
                </button>

                <button
                  class="px-2 py-1 rounded-lg border border-border bg-glass2 text-[11px] text-text1 cursor-pointer"
                  onclick={() => (weekPickerValue = format(addDays(selectedWeekStart, 7), 'yyyy-MM-dd'))}
                  aria-label="Next week"
                >
                  →
                </button>
              </div>
            </div>
          </Card>

          {#if weekWorkouts.length === 0}
            <Card style="padding: 14px;">
              <p class="text-[12px] text-text2">No workouts logged in this week.</p>
            </Card>
          {/if}

          {#each weekWorkouts as w (w?.id ?? w?.started_at)}
            <button class="text-left bg-transparent border-none p-0 cursor-pointer w-full" onclick={() => selectedWorkout = w}>
              <Card style="padding: 12px 14px;">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center text-[18px] {getWorkoutBg(w.sport)}">
                    {getWorkoutIcon(w.sport)}
                  </div>
                  <div class="flex-1">
                    <p class="text-[13px] font-semibold">{w.title || (getWorkoutLabel(w.sport) + ' Session')}</p>
                    <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(getDurationSecs(w) / 60)} min</p>
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
