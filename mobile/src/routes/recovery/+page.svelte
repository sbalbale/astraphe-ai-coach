<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { normalizeUnits, type Units } from '$lib/utils/units';
  import { onMount } from 'svelte';
  import { addDays, format, subDays } from 'date-fns';
  import { page } from '$app/stores';

  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  
  type BiometricsRecord = Record<string, any> & { date?: string };
  type TrainingLoadRecord = { date: string; daily_tss?: number | null; atl?: number | null };
  
  function isFiniteNumber(v: unknown): v is number {
    return typeof v === 'number' && Number.isFinite(v);
  }
  
  function formatSignedInt(delta: number | null | undefined): string {
    if (!isFiniteNumber(delta)) return '--';
    const d = Math.round(delta);
    if (Math.abs(d) < 1) return '~';
    return d > 0 ? `+${d}` : `${d}`;
  }
  
  function formatTempDeviationF(v: number | null | undefined): string {
    if (!isFiniteNumber(v)) return '--';
    const r = Math.round(v * 10) / 10;
    const sign = r > 0 ? '+' : r < 0 ? '' : '';
    return `${sign}${r.toFixed(1)}°F`;
  }

  function formatSigned1dp(delta: number | null | undefined, unit: string): string {
    if (!isFiniteNumber(delta)) return '--';
    const r = Math.round(delta * 10) / 10;
    if (Math.abs(r) < 0.05) return `~0.0${unit}`;
    const sign = r > 0 ? '+' : '';
    return `${sign}${r.toFixed(1)}${unit}`;
  }

  function cToF(c: number): number {
    return (c * 9) / 5 + 32;
  }

  function deltaCToF(dc: number): number {
    return (dc * 9) / 5;
  }

  function hexToRgba(hex: string, alpha: number): string {
    const h = hex.replace('#', '').trim();
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    const n = Number.parseInt(full, 16);
    if (!Number.isFinite(n)) return `rgba(255,255,255,${alpha})`;
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `rgba(${r},${g},${b},${alpha})`;
  }

  const FACTOR_COLORS = {
    hrv: '#00C8A8',
    rhr: '#7C3AED',
    sleep: '#FFCB88',
    load: '#F07178',
    temp: '#00C8A8',
    spo2: '#7C3AED'
  } as const;
  
  function baselineAvg30d(series: BiometricsRecord[] | undefined, endDateStr: string, field: string): number | null {
    if (!series?.length) return null;
    const end = new Date(endDateStr + 'T00:00:00');
    if (Number.isNaN(end.getTime())) return null;
    // Baseline should be the 30 days *prior* to the selected day (exclude current day).
    const endExclusive = subDays(end, 1);
    const start = subDays(endExclusive, 29);
    
    const vals = series
      .filter((r) => {
        if (!r?.date) return false;
        const dt = new Date(r.date + 'T00:00:00');
        if (Number.isNaN(dt.getTime())) return false;
        return dt >= start && dt <= endExclusive;
      })
      .map((r) => Number((r as any)[field]))
      .filter((v) => Number.isFinite(v) && v !== 0);
    
    if (vals.length === 0) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }
  
  function signedDeltaVsBaseline(series: BiometricsRecord[] | undefined, endDateStr: string, field: string, todayValue: number | null): number | null {
    if (!isFiniteNumber(todayValue)) return null;
    const base = baselineAvg30d(series, endDateStr, field);
    if (!isFiniteNumber(base)) return null;
    return todayValue - base;
  }
  
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

  const units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));
  const isImperial = $derived(units === 'imperial');
  
  const biometricsSeries = $derived(athleteStore.biometrics?.series as BiometricsRecord[] | undefined);
  
  const hrvToday = $derived(isFiniteNumber(d?.data?.hrv_rmssd) ? Math.round(d.data.hrv_rmssd) : null);
  const hrvBaseline = $derived.by(() => {
    const base = baselineAvg30d(biometricsSeries, d.date, 'hrv_rmssd');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const hrvDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'hrv_rmssd', hrvToday));
  const hrvGood = $derived.by(() => (hrvDelta === null ? null : hrvDelta >= 0));
  
  const rhrToday = $derived(isFiniteNumber(d?.data?.resting_hr) ? Math.round(d.data.resting_hr) : null);
  const rhrBaseline = $derived.by(() => {
    const base = baselineAvg30d(biometricsSeries, d.date, 'resting_hr');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const rhrDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'resting_hr', rhrToday));
  const rhrGood = $derived.by(() => (rhrDelta === null ? null : rhrDelta <= 0));
  
  const sleepScoreToday = $derived(isFiniteNumber(d?.data?.sleep_score) ? Math.round(d.data.sleep_score) : null);
  const sleepBaseline = $derived.by(() => {
    const base = baselineAvg30d(biometricsSeries, d.date, 'sleep_score');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const sleepDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'sleep_score', sleepScoreToday));
  const sleepGood = $derived.by(() => (sleepDelta === null ? null : sleepDelta >= 0));
  
  const sleepHours = $derived.by(() => (isFiniteNumber(d?.data?.sleep_duration_min) ? Math.round((d.data.sleep_duration_min / 60) * 10) / 10 : null));
  const sleepDeepPct = $derived.by(() => (isFiniteNumber(d?.data?.sleep_deep_pct) ? Math.round(d.data.sleep_deep_pct) : null));
  
  const priorLoad = $derived.by(() => {
    const series = athleteStore.metrics?.trainingLoadData as TrainingLoadRecord[] | undefined;
    if (!series?.length || !d?.date) return null;
    const priorDate = format(subDays(new Date(d.date + 'T00:00:00'), 1), 'yyyy-MM-dd');
    const priorDay = series.find((x) => x.date === priorDate);
    if (!priorDay) return null;
    
    const end = new Date(priorDate + 'T00:00:00');
    const start = subDays(end, 29);
    const inRange = series.filter((x) => {
      const dt = new Date(x.date + 'T00:00:00');
      if (Number.isNaN(dt.getTime())) return false;
      return dt >= start && dt <= end && isFiniteNumber(x.atl);
    });
    const peakAtl30d = inRange.length ? Math.max(...inRange.map((x) => Number(x.atl))) : null;
    const deltaDrop = isFiniteNumber(priorDay.atl) && isFiniteNumber(peakAtl30d) ? Math.round(Number(priorDay.atl) - Number(peakAtl30d)) : null;
    
    let trend = '--';
    if (isFiniteNumber(deltaDrop)) {
      if (Math.abs(deltaDrop) < 5) trend = '~';
      else trend = deltaDrop < 0 ? `↓${Math.abs(deltaDrop)}` : `↑${deltaDrop}`;
    }
    
    return {
      priorDate,
      dailyTss: isFiniteNumber(priorDay.daily_tss) ? Math.round(Number(priorDay.daily_tss)) : null,
      deltaDrop,
      trend
    };
  });
  
  // NOTE: `skin_temp_deviation` is stored as *skin/body temperature in °C* for WHOOP recovery payloads.
  // We treat it as an actual temperature measurement and show deviation vs baseline.
  const bodyTempCToday = $derived(isFiniteNumber(d?.data?.skin_temp_deviation) ? Number(d.data.skin_temp_deviation) : null);
  const bodyTempCBaseline = $derived.by(() => {
    const base = baselineAvg30d(biometricsSeries, d.date, 'skin_temp_deviation');
    if (!isFiniteNumber(base)) return null;
    return Math.round(base * 10) / 10;
  });
  const bodyTempCDelta = $derived.by(() => {
    if (!isFiniteNumber(bodyTempCToday) || !isFiniteNumber(bodyTempCBaseline)) return null;
    return bodyTempCToday - bodyTempCBaseline;
  });

  const bodyTempDisplay = $derived.by(() => {
    if (!isFiniteNumber(bodyTempCToday)) return null;
    const val = isImperial ? cToF(bodyTempCToday) : bodyTempCToday;
    return Math.round(val * 10) / 10;
  });

  const bodyTempBaselineDisplay = $derived.by(() => {
    if (!isFiniteNumber(bodyTempCBaseline)) return null;
    const val = isImperial ? cToF(bodyTempCBaseline) : bodyTempCBaseline;
    return Math.round(val * 10) / 10;
  });

  const bodyTempDeltaDisplay = $derived.by(() => {
    if (!isFiniteNumber(bodyTempCDelta)) return null;
    const val = isImperial ? deltaCToF(bodyTempCDelta) : bodyTempCDelta;
    return Math.round(val * 10) / 10;
  });

  const spo2Pct = $derived(isFiniteNumber(d?.data?.spo2_pct) ? Math.round(d.data.spo2_pct) : null);
  const spo2Baseline = $derived.by(() => {
    const base = baselineAvg30d(biometricsSeries, d.date, 'spo2_pct');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const spo2Delta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'spo2_pct', spo2Pct));

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
      
      <!-- Contributing Factors -->
      <Card style="padding: 14px;">
        <div class="flex items-center justify-between mb-3">
          <p class="text-[13px] font-semibold">Contributing Factors</p>
          <span class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">vs 30d</span>
        </div>

        <div class="flex flex-col gap-3">
          <!-- HRV -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">HRV</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {hrvGood === null ? 'var(--text2)' : FACTOR_COLORS.hrv}; opacity: {hrvGood === null ? 0.8 : 1}">
                  {formatSignedInt(hrvDelta)}
                </span>
                <span class="text-[12px] font-semibold" style="color: {hrvToday === null ? 'var(--text2)' : FACTOR_COLORS.hrv}">
                  {hrvToday === null ? '--' : `${hrvToday}ms`}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.hrv, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.hrv}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {hrvToday === null
                ? 'Not available for this day.'
                : hrvBaseline === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : hrvDelta !== null && hrvDelta >= 0
                    ? `Above your 30-day baseline of ${hrvBaseline}ms. Strong parasympathetic response.`
                    : `Below your 30-day baseline of ${hrvBaseline}ms. Lower HRV can reflect accumulated stress.`}
            </p>
          </div>

          <!-- Resting HR -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Resting HR</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {rhrGood === null ? 'var(--text2)' : FACTOR_COLORS.rhr}; opacity: {rhrGood === null ? 0.8 : 1}">
                  {formatSignedInt(rhrDelta)}
                </span>
                <span class="text-[12px] font-semibold" style="color: {rhrToday === null ? 'var(--text2)' : FACTOR_COLORS.rhr}">
                  {rhrToday === null ? '--' : `${rhrToday}bpm`}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.rhr, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.rhr}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {rhrToday === null
                ? 'Not available for this day.'
                : rhrBaseline === null || rhrDelta === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : rhrDelta < 0
                    ? `${Math.abs(Math.round(rhrDelta))} bpm below baseline. Low resting HR indicates good cardiac efficiency.`
                    : `${Math.round(rhrDelta)} bpm above baseline. Elevated RHR can reflect fatigue or stress.`}
            </p>
          </div>

          <!-- Sleep Quality -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Sleep Quality</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {sleepGood === null ? 'var(--text2)' : FACTOR_COLORS.sleep}; opacity: {sleepGood === null ? 0.8 : 1}">
                  {formatSignedInt(sleepDelta)}
                </span>
                <span class="text-[12px] font-semibold" style="color: {sleepScoreToday === null ? 'var(--text2)' : FACTOR_COLORS.sleep}">
                  {sleepScoreToday === null ? '--' : `${sleepScoreToday}%`}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.sleep, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.sleep}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {sleepScoreToday === null
                ? 'Not available for this day.'
                : `${sleepHours === null ? '--' : sleepHours}h with ${sleepScoreToday}% quality.${sleepDeepPct === null ? '' : ` Deep sleep at ${sleepDeepPct}% — excellent for recovery.`}`}
            </p>
          </div>

          <!-- Prior Load -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Prior Load</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {priorLoad === null ? 'var(--text2)' : FACTOR_COLORS.load}; opacity: {priorLoad === null ? 0.8 : 1}">
                  {priorLoad === null ? '--' : priorLoad.trend}
                </span>
                <span class="text-[12px] font-semibold" style="color: {priorLoad?.dailyTss == null ? 'var(--text2)' : FACTOR_COLORS.load}">
                  {priorLoad?.dailyTss == null ? '--' : `${priorLoad.dailyTss}TSS`}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.load, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.load}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {priorLoad === null
                ? 'Not available for this day.'
                : priorLoad.deltaDrop === null
                  ? 'Load trend not available yet.'
                  : priorLoad.deltaDrop < 0
                    ? `Yesterday was a recovery day. Acute load dropped ${Math.abs(priorLoad.deltaDrop)} pts from peak.`
                    : priorLoad.deltaDrop > 0
                      ? `Yesterday pushed load higher. Acute load rose ${priorLoad.deltaDrop} pts vs peak.`
                      : 'Acute load stayed steady vs your recent peak.'}
            </p>
          </div>

          <!-- Body Temp -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">Body Temp</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {bodyTempDeltaDisplay === null ? 'var(--text2)' : FACTOR_COLORS.temp}; opacity: {bodyTempDeltaDisplay === null ? 0.8 : 1}">
                  {bodyTempDeltaDisplay === null ? '--' : '~'}
                </span>
                <span class="text-[12px] font-semibold" style="color: {bodyTempDeltaDisplay === null ? 'var(--text2)' : FACTOR_COLORS.temp}">
                  {bodyTempDeltaDisplay === null ? '--' : formatSigned1dp(bodyTempDeltaDisplay, isImperial ? '°F' : '°C')}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.temp, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.temp}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {bodyTempCToday === null
                ? 'Not available for this day.'
                : bodyTempBaselineDisplay === null || bodyTempDeltaDisplay === null || bodyTempDisplay === null
                  ? `Body temp recorded at ${Math.round((bodyTempDisplay ?? (isImperial ? cToF(bodyTempCToday) : bodyTempCToday)) * 10) / 10}${isImperial ? '°F' : '°C'}. Baseline not available yet.`
                  : Math.abs(bodyTempDeltaDisplay) > (isImperial ? 0.9 : 0.5)
                    ? `Temp elevated vs baseline (${bodyTempBaselineDisplay}${isImperial ? '°F' : '°C'}). Monitor for signs of illness or overheating.`
                    : `Temp stable vs baseline (${bodyTempBaselineDisplay}${isImperial ? '°F' : '°C'}). No signs of illness or overheating.`}
            </p>
          </div>

          <!-- SPO2 -->
          <div class="flex flex-col gap-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-[10px] text-text2 font-mono uppercase tracking-[0.1em]">SPO2</p>
              </div>
              <div class="shrink-0 flex flex-col items-end leading-tight">
                <span class="text-[11px] font-mono" style="color: {spo2Delta === null ? 'var(--text2)' : FACTOR_COLORS.spo2}; opacity: {spo2Delta === null ? 0.8 : 1}">
                  {formatSignedInt(spo2Delta)}
                </span>
                <span class="text-[12px] font-semibold" style="color: {spo2Pct === null ? 'var(--text2)' : FACTOR_COLORS.spo2}">
                  {spo2Pct === null ? '--' : `${spo2Pct}%`}
                </span>
              </div>
            </div>
            <div class="h-[3px] rounded-full overflow-hidden" style="background: {hexToRgba(FACTOR_COLORS.spo2, 0.25)}">
              <div class="h-full w-full rounded-full" style="background: {FACTOR_COLORS.spo2}"></div>
            </div>
            <p class="text-[11px] text-text2 leading-snug">
              {spo2Pct === null
                ? 'Not available for this day.'
                : spo2Baseline === null || spo2Delta === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : spo2Pct < 94
                    ? 'Blood oxygen dipped below normal overnight. Consider sleep position, altitude, or congestion.'
                    : spo2Delta >= 0
                      ? `Above your 30-day baseline of ${spo2Baseline}%. Blood oxygen within normal range all night.`
                      : `Below your 30-day baseline of ${spo2Baseline}%. Blood oxygen slightly reduced overnight.`}
            </p>
          </div>
        </div>
      </Card>

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
