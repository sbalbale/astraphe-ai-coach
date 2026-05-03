<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const strainAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
  import { addDays, format, subDays } from 'date-fns';
  import { strainTextClass, tssTextClass } from '$lib/scoreColors';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state('');
  let dayIndex = $state(6); // most recent on the right
  const isoDate = (value: unknown) => (typeof value === 'string' ? value.slice(0, 10) : '');

  const today = $derived(new Date());
  const todayStr = $derived(format(today, 'yyyy-MM-dd'));

  $effect(() => {
    if (!endPickerValue) {
      endPickerValue = todayStr;
      dayIndex = 6;
    }
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
    // Build oldest→newest for display (today on the right).
    const asc = Array.from({ length: 7 }, (_, i) => {
      const d = addDays(windowStart, i);
      const dateStr = format(d, 'yyyy-MM-dd');
      
      const b = athleteStore.biometrics?.series?.find((s: any) => s.date === dateStr);
      const history = athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === dateStr);
      const dow = format(d, 'EE');
      const dayLabel = dow === 'Thu' ? 'Th' : dow.charAt(0);
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
        day: dayLabel,
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
    return asc;
  });

  $effect(() => {
    dayIndex = Math.max(0, Math.min(6, dayIndex ?? 0));
  });

  const d = $derived(days[dayIndex]);
  const hasData = $derived(days.some(day => !day.missing) || athleteStore.atl > 0);
  
  const score = $derived(d.score || 0);
  // Strain is inverted: higher strain = "worse" (red).
  const scoreColor = $derived(score >= 67 ? '#F07178' : score >= 34 ? '#FFCB88' : '#00C8A8');
  const quality = $derived(score >= 67 ? 'High' : score >= 34 ? 'Moderate' : 'Light');

  const avg7d = $derived.by(() => {
    const vals = days.map((x) => Number(x.score)).filter((v) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
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

  function getDurationSecs(w: any): number {
    const direct = w?.duration_secs ?? w?.duration_seconds;
    if (Number.isFinite(direct)) return Math.max(0, Math.floor(Number(direct)));
    return 0;
  }

  type ZoneBreakdown = {
    validSeconds: number;
    zoneSeconds: number[]; // index = zone 0..5
    zonePct: number[]; // index = zone 0..5
  };

  function computeZoneBreakdown(workouts: any[]): ZoneBreakdown {
    const zoneSeconds = [0, 0, 0, 0, 0, 0];
    let validSeconds = 0;

    for (let i = 0; i < workouts.length; i++) {
      const w = workouts[i];
      // We treat zone data as present if at least Z1 exists (matches other pages' convention).
      if (w?.hr_zone_1_pct === null || w?.hr_zone_1_pct === undefined) continue;

      const duration = getDurationSecs(w);
      if (!duration) continue;

      const z1 = Number(w?.hr_zone_1_pct || 0);
      const z2 = Number(w?.hr_zone_2_pct || 0);
      const z3 = Number(w?.hr_zone_3_pct || 0);
      const z4 = Number(w?.hr_zone_4_pct || 0);
      const z5 = Number(w?.hr_zone_5_pct || 0);
      const z0 = Math.max(0, 100 - (z1 + z2 + z3 + z4 + z5));

      const pcts = [z0, z1, z2, z3, z4, z5];
      for (let z = 0; z <= 5; z++) zoneSeconds[z] += (duration * pcts[z]) / 100;
      validSeconds += duration;
    }

    if (!validSeconds) return { validSeconds: 0, zoneSeconds, zonePct: [0, 0, 0, 0, 0, 0] };

    // Round to whole % and normalize so it sums to exactly 100.
    let zonePct = zoneSeconds.map((s) => Math.round((s / validSeconds) * 100));
    let sum = zonePct.reduce((a, b) => a + b, 0);
    if (sum !== 100 && sum > 0) {
      const maxIdx = zonePct.indexOf(Math.max(...zonePct));
      zonePct[maxIdx] += 100 - sum;
    }

    return { validSeconds, zoneSeconds, zonePct };
  }

  let selectedWorkout = $state<any>(null);
  let showWorkoutModal = $state(false);

  function openWorkoutDetails(w: any) {
    selectedWorkout = w;
    showWorkoutModal = true;
  }

  const dayZones = $derived.by(() => computeZoneBreakdown(d?.workouts || []));

  const formatMinutes = (secs: number) => {
    const m = Math.round(Math.max(0, secs) / 60);
    return m < 1 ? '0m' : `${m}m`;
  };

  let analysisText = $state<string | null>(null);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    // Re-run when store finishes loading so an early unauthenticated/empty fetch can't strand us on null.
    void athleteStore.initialLoadDone;
    void athleteStore.loading;
    void d?.tsb;
    void d?.score;

    const day = d?.date;
    if (!day) {
      analysisText = null;
      return;
    }

    const cached = strainAnalysisMemo.get(day);
    if (cached !== undefined && cached !== null) {
      analysisText = cached;
      return;
    }

    analysisText = null;

    const requestKey = `strain:${day}`;
    activeAnalysisKey = requestKey;

    (async () => {
      const res = await api.getStrainAnalysis(day);
      const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
      const next = content ? content : null;
      if (next) strainAnalysisMemo.set(day, next);

      if (activeAnalysisKey !== requestKey) return;
      analysisText = next;
    })();
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Physical Load</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Strain</h1>
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
          <p class="text-[14px] font-bold mb-1">No strain data for {d.date}</p>
          <p class="text-[11px] text-text2 max-w-[200px]">
            We couldn't find any activity or biometric records for this day.
          </p>
        </div>
      </Card>
    {:else}
      <!-- Hero Card (Sleep Page Style) -->
      <Card style="background: var(--glass); border-color: var(--border);">
        <div class="flex items-center gap-4">
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
              <span class="text-[18px] font-bold">{quality}</span>
              <Tag color={scoreColor}>{score >= 67 ? 'HIGH' : score >= 34 ? 'PRODUCTIVE' : 'BASE'}</Tag>
            </div>
            <p class="text-xs text-text1 leading-relaxed">
              {score >= 67 ? 'Your training volume is significantly higher than your baseline.' : 
               score >= 34 ? 'Productive stress detected. You are building fitness efficiently.' : 
               'Light recovery day. Focus on maintaining aerobic foundation.'}
            </p>
          </div>
        </div>
      </Card>

      <!-- Metrics Grid -->
      <div class="grid grid-cols-3 gap-2">
        <Card style="padding: 8px 10px;">
          <MetricBadge label="Fatigue" value={Math.round(d.atl)} unit="" color="var(--amber)" sub="ATL" />
        </Card>
        <Card style="padding: 8px 10px;">
          <MetricBadge label="Fitness" value={Math.round(d.ctl)} unit="" color="var(--teal)" sub="CTL" />
        </Card>
        <Card style="padding: 8px 10px;">
          <MetricBadge label="Form" value={Math.round(d.tsb)} unit="" color="var(--blue)" sub="TSB" />
        </Card>
      </div>

      <!-- Timeline -->
      <Card>
        <div class="flex justify-between items-center mb-3">
          <p class="text-[13px] font-semibold">7-Day Trend</p>
          <span class="text-[10px] text-text2 font-mono">
            avg {avg7d === null ? '--' : `${avg7d}%`} · {score}% current
          </span>
        </div>
        <div class="flex gap-2 items-end h-[50px] mb-1 px-1">
          {#each days as day, i (day.date)}
            {@const c = day.score >= 67 ? '#F07178' : day.score >= 34 ? '#FFCB88' : '#00C8A8'}
            <button
              type="button"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer"
              onclick={() => (dayIndex = i)}
              aria-label={`Select ${day.label}: ${day.score}%`}
            >
              <div class="w-full rounded-t-sm transition-all duration-300" 
                   style="background: {i === dayIndex ? c : c + '44'}; height: {Math.max(4, (day.score / 100) * 50)}px;"></div>
              <span class="text-[9px] font-mono {i === dayIndex ? 'text-text0' : 'text-text2'}">{day.day}</span>
            </button>
          {/each}
        </div>
      </Card>

      {#if dayZones.validSeconds > 0}
        <Card>
          <div class="flex justify-between items-center mb-3">
            <p class="text-[13px] font-semibold">Heart Rate Zones</p>
            <span class="text-[10px] text-text2 font-mono">
              {formatMinutes(dayZones.validSeconds)} total
            </span>
          </div>
          <div class="flex flex-col gap-3">
            {#each [5, 4, 3, 2, 1, 0] as zone (zone)}
              {@const pct = dayZones.zonePct[zone] || 0}
              {@const secs = dayZones.zoneSeconds[zone] || 0}
              <div class="flex items-center gap-3">
                <div class="w-9 flex items-center gap-1.5 shrink-0">
                  <div class="w-2 h-2 rounded-full" style="background: var(--zone-{zone})"></div>
                  <span class="text-[10px] font-mono text-text2">Z{zone}</span>
                </div>
                <div class="flex-1 h-1.5 bg-glass rounded-full overflow-hidden relative">
                  <div
                    class="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                    style="width: {pct}%; background: var(--zone-{zone})"
                  ></div>
                </div>
                <div class="w-[84px] text-right shrink-0">
                  <span class="text-[11px] font-bold font-mono {pct > 0 ? 'text-text1' : 'text-text3'}">
                    {formatMinutes(secs)} · {pct}%
                  </span>
                </div>
              </div>
            {/each}
          </div>
          <p class="text-[10px] text-text2 italic mt-3 text-center">
            Aggregated from sessions on {d.date} with zone data.
          </p>
        </Card>
      {/if}

      {#if d.workouts && d.workouts.length > 0}
        <div>
          <p class="text-[11px] text-text2 font-mono uppercase tracking-[0.05em] mb-2 px-1">Contributing Activities</p>
          <div class="flex flex-col gap-2">
            {#each d.workouts as w (w.id || w.started_at)}
              {@const strainVal = Number.isFinite(Number(w?.strain_score)) ? Math.round(Number(w.strain_score)) : null}
              {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
              <button 
                type="button"
                class="block w-full text-left active:scale-[0.98] transition-transform"
                onclick={() => openWorkoutDetails(w)}
              >
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
                    <div class="text-right flex flex-col gap-1">
                      <div>
                        <p class="text-[14px] font-bold {strainVal === null ? 'text-text2' : strainTextClass(strainVal)}">
                          {strainVal === null ? '--' : strainVal}
                        </p>
                        <p class="text-[9px] text-text2 font-mono">STRAIN</p>
                      </div>
                      <div>
                        <p class="text-[14px] font-bold {tssVal === null ? 'text-text2' : tssTextClass(tssVal)}">
                          {tssVal === null ? '--' : tssVal}
                        </p>
                        <p class="text-[9px] text-text2 font-mono">TSS</p>
                      </div>
                    </div>
                  </div>
                </Card>
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Analysis Card -->
      <Card
        style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);"
      >
        <p class="text-[13px] font-semibold mb-1.5">Strain Analysis</p>
        <p class="text-xs text-text1 leading-relaxed">
          {analysisText ??
            (d.tsb < -20
              ? 'Your training form is highly negative. Prioritize active recovery sessions.'
              : d.tsb > 10
                ? 'Your body is fresh and primed for a high-intensity block. CTL is stable.'
                : 'Your training volume is well-balanced with your current fitness level.')}
        </p>
      </Card>
    {/if}
  {/if}
</div>

<Modal
  show={showWorkoutModal}
  title={selectedWorkout?.title || (getWorkoutLabel(selectedWorkout?.sport) + ' Details')}
  onClose={() => (showWorkoutModal = false)}
>
  {#if selectedWorkout}
    {@const selectedStrainVal = Number.isFinite(Number(selectedWorkout?.strain_score)) ? Math.round(Number(selectedWorkout.strain_score)) : null}
    {@const selectedTssVal = Number.isFinite(Number(selectedWorkout?.tss)) ? Math.round(Number(selectedWorkout.tss)) : null}
    <div class="flex flex-col gap-6">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-2xl flex items-center justify-center text-[28px] {getWorkoutBg(selectedWorkout.sport)}">
          {getWorkoutIcon(selectedWorkout.sport)}
        </div>
        <div>
          <h3 class="text-lg font-bold">{selectedWorkout.title || (getWorkoutLabel(selectedWorkout.sport) + ' Session')}</h3>
          <p class="text-xs text-text2 font-mono uppercase">
            {format(new Date(selectedWorkout.started_at), 'MMMM d, yyyy')} · {format(new Date(selectedWorkout.started_at), (athleteStore.profile as any)?.time_format === '24h' ? 'HH:mm' : 'h:mm a')}
          </p>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Intensity</p>
          <div class="flex items-baseline gap-1">
            <span class="text-[20px] font-bold {selectedStrainVal === null ? 'text-text2' : strainTextClass(selectedStrainVal)}">
              {selectedStrainVal === null ? '--' : selectedStrainVal}
            </span>
            <span class="text-[10px] text-text2 font-mono">STRAIN</span>
          </div>
        </div>
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Duration</p>
          <div class="flex items-baseline gap-1">
            <span class="text-[20px] font-bold text-text0">{Math.floor(getDurationSecs(selectedWorkout) / 60)}</span>
            <span class="text-[10px] text-text2 font-mono">MIN</span>
          </div>
        </div>
        {#if selectedWorkout.avg_hr}
          <div class="p-4 rounded-2xl bg-glass border border-border/50">
            <p class="text-[10px] text-text2 font-mono uppercase mb-1">Avg HR</p>
            <div class="flex items-baseline gap-1">
              <span class="text-[20px] font-bold text-text0">{selectedWorkout.avg_hr}</span>
              <span class="text-[10px] text-text2 font-mono">BPM</span>
            </div>
          </div>
        {/if}
        <div class="p-4 rounded-2xl bg-glass border border-border/50">
          <p class="text-[10px] text-text2 font-mono uppercase mb-1">Stress</p>
          <div class="flex items-baseline gap-1">
            <span class="text-[20px] font-bold {selectedTssVal === null ? 'text-text2' : tssTextClass(selectedTssVal)}">
              {selectedTssVal === null ? '--' : selectedTssVal}
            </span>
            <span class="text-[10px] text-text2 font-mono">TSS</span>
          </div>
        </div>
        {#if selectedWorkout.distance_m}
          <div class="p-4 rounded-2xl bg-glass border border-border/50">
            <p class="text-[10px] text-text2 font-mono uppercase mb-1">Distance</p>
            <div class="flex items-baseline gap-1">
              <span class="text-[20px] font-bold text-text0">{(selectedWorkout.distance_m / 1000).toFixed(2)}</span>
              <span class="text-[10px] text-text2 font-mono">KM</span>
            </div>
          </div>
        {/if}
      </div>

      {#if selectedWorkout.hr_zone_0_pct !== undefined || selectedWorkout.hr_zone_1_pct !== undefined || selectedWorkout.hr_zone_2_pct !== undefined}
        <div class="flex flex-col gap-4">
          <p class="text-[13px] font-semibold">Heart Rate Zones</p>
          <div class="flex flex-col gap-3">
            {#each [5, 4, 3, 2, 1, 0] as zone (zone)}
              {@const pct = selectedWorkout[`hr_zone_${zone}_pct`] || 0}
              <div class="flex items-center gap-3">
                <div class="w-8 flex items-center gap-1.5 shrink-0">
                  <div class="w-2 h-2 rounded-full" style="background: var(--zone-{zone})"></div>
                  <span class="text-[10px] font-mono text-text2">Z{zone}</span>
                </div>
                <div class="flex-1 h-1.5 bg-glass rounded-full overflow-hidden relative">
                   <div 
                    class="absolute inset-y-0 left-0 rounded-full transition-all duration-500" 
                    style="width: {pct}%; background: var(--zone-{zone})"
                  ></div>
                </div>
                <div class="w-8 text-right shrink-0">
                  <span class="text-[11px] font-bold font-mono {pct > 0 ? 'text-text1' : 'text-text3'}">{pct}%</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <div class="p-4 rounded-xl bg-glass border border-border/50 flex flex-col gap-2">
         <div class="flex justify-between items-center">
            <span class="text-xs text-text2">Source</span>
            <span class="text-xs font-mono font-medium text-text1 uppercase">{selectedWorkout.source || 'Manual'}</span>
         </div>
         {#if selectedWorkout.norm_power_w}
          <div class="flex justify-between items-center">
              <span class="text-xs text-text2">Normalized Power</span>
              <span class="text-xs font-mono font-medium text-text1">{selectedWorkout.norm_power_w} W</span>
          </div>
         {/if}
      </div>
    </div>
  {/if}
</Modal>
