<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const recoveryAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import Pill from '$lib/components/Pill.svelte';
  import DatePicker from '$lib/components/DatePicker.svelte';
  import TrendIndicator from '$lib/components/TrendIndicator.svelte';
  import DeviationTrack from '$lib/components/DeviationTrack.svelte';
  import { boundedScoreCssColor, zScoreCssColor } from '$lib/scoreColors';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { api } from '$lib/api';
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
  
  function formatSigned1dp(delta: number | null | undefined, unit: string): string {
    if (!isFiniteNumber(delta)) return '--';
    const r = Math.round(delta * 10) / 10;
    if (Math.abs(r) < 0.05) return `~0.0${unit}`;
    const sign = r > 0 ? '+' : '';
    return `${sign}${r.toFixed(1)}${unit}`;
  }

  function formatHoursMinutesFromMinutes(mins: number | null | undefined): string {
    const n = typeof mins === 'number' ? mins : Number(mins);
    if (!Number.isFinite(n)) return '--';
    const m = Math.max(0, Math.round(n));
    const h = Math.floor(m / 60);
    const r = m % 60;
    return `${h}h ${r}m`;
  }

  function cToF(c: number): number {
    return (c * 9) / 5 + 32;
  }

  function deltaCToF(dc: number): number {
    return (dc * 9) / 5;
  }

  function baselineWindowVals(series: BiometricsRecord[] | undefined, endDateStr: string, field: string, days: number): number[] {
    if (!series?.length) return [];
    const end = new Date(endDateStr + 'T00:00:00');
    if (Number.isNaN(end.getTime())) return [];
    // Baseline excludes the selected day so today's value can't bias its own baseline.
    const endExclusive = subDays(end, 1);
    const start = subDays(endExclusive, Math.max(0, days - 1));
    return series
      .filter((r) => {
        if (!r?.date) return false;
        const dt = new Date(r.date + 'T00:00:00');
        if (Number.isNaN(dt.getTime())) return false;
        return dt >= start && dt <= endExclusive;
      })
      .map((r) => Number((r as any)[field]))
      .filter((v) => Number.isFinite(v) && v !== 0);
  }

  function baselineAvg(series: BiometricsRecord[] | undefined, endDateStr: string, field: string, days: number): number | null {
    const vals = baselineWindowVals(series, endDateStr, field, days);
    if (vals.length === 0) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }

  function baselineAvg7d(series: BiometricsRecord[] | undefined, endDateStr: string, field: string): number | null {
    return baselineAvg(series, endDateStr, field, 7);
  }
  
  function signedDeltaVsBaseline(series: BiometricsRecord[] | undefined, endDateStr: string, field: string, todayValue: number | null, days = 7): number | null {
    if (!isFiniteNumber(todayValue)) return null;
    const base = baselineAvg(series, endDateStr, field, days);
    if (!isFiniteNumber(base)) return null;
    return todayValue - base;
  }

  // Local z-score helper for fields the backend doesn't ship `*_z` for
  // (body temp, SpO2). Uses a 7-day baseline + sample stddev — same window
  // the backend's HRV/RHR EWMA uses, so the deviation track's center is
  // semantically equivalent across all four vitals.
  function zScoreFromSeries(series: BiometricsRecord[] | undefined, endDateStr: string, field: string, todayValue: number | null, days = 7): number | null {
    if (!isFiniteNumber(todayValue)) return null;
    const vals = baselineWindowVals(series, endDateStr, field, days);
    if (vals.length < 3) return null;
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, vals.length - 1);
    const sd = Math.sqrt(variance);
    if (!Number.isFinite(sd) || sd <= 1e-6) return null;
    return (todayValue - mean) / sd;
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
  const scoreColor = $derived(boundedScoreCssColor(score));
  const quality = $derived(score >= 67 ? 'Optimal' : score >= 34 ? 'Moderate' : 'Fatigued');

  // HRV / RHR z-scores come straight off the biometrics row (computed on the
  // backend in /v1/biometrics with a single-pass running EWMA span=7).
  const hrvZ = $derived(
    typeof d?.data?.hrv_z === 'number' && Number.isFinite(d.data.hrv_z) ? Number(d.data.hrv_z) : null
  );
  const rhrZ = $derived(
    typeof d?.data?.rhr_z === 'number' && Number.isFinite(d.data.rhr_z) ? Number(d.data.rhr_z) : null
  );

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
    const base = baselineAvg7d(biometricsSeries, d.date, 'hrv_rmssd');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const hrvDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'hrv_rmssd', hrvToday, 7));

  const rhrToday = $derived(isFiniteNumber(d?.data?.resting_hr) ? Math.round(d.data.resting_hr) : null);
  const rhrBaseline = $derived.by(() => {
    const base = baselineAvg7d(biometricsSeries, d.date, 'resting_hr');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const rhrDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'resting_hr', rhrToday, 7));

  const sleepScoreToday = $derived(isFiniteNumber(d?.data?.sleep_score) ? Math.round(d.data.sleep_score) : null);
  const sleepDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'sleep_score', sleepScoreToday, 7));
  
  const sleepDurationMin = $derived.by(() => (isFiniteNumber(d?.data?.sleep_duration_min) ? Math.round(d.data.sleep_duration_min) : null));
  const sleepDurationHM = $derived.by(() => (sleepDurationMin === null ? null : formatHoursMinutesFromMinutes(sleepDurationMin)));
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
  
  // NOTE: `skin_temp` stores *skin/body temperature in °C*.
  // We treat it as an actual temperature measurement and show deviation vs baseline.
  const bodyTempCToday = $derived(isFiniteNumber(d?.data?.skin_temp) ? Number(d.data.skin_temp) : null);
  const bodyTempCBaseline = $derived.by(() => {
    const base = baselineAvg7d(biometricsSeries, d.date, 'skin_temp');
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
    const base = baselineAvg7d(biometricsSeries, d.date, 'spo2_pct');
    return isFiniteNumber(base) ? Math.round(base) : null;
  });
  const spo2Delta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'spo2_pct', spo2Pct, 7));

  // Locally-computed z-scores for vitals the backend doesn't ship explicit
  // `*_z` fields for. Used to drive the colored deviation track + delta
  // coloring on the Contributing Factors panel.
  const bodyTempZ = $derived(zScoreFromSeries(biometricsSeries, d.date, 'skin_temp', bodyTempCToday));
  const spo2Z = $derived(zScoreFromSeries(biometricsSeries, d.date, 'spo2_pct', spo2Pct));

  // Prior day's strain score (0-100) drives the bar fill + delta color for
  // the "Prior Load" row. We still display the raw TSS as the value text,
  // because TSS is the unit athletes recognise — strain just gives us a
  // bounded score we can apply the rule of thirds to.
  const priorStrainScore = $derived.by(() => {
    if (!biometricsSeries?.length || !d?.date) return null;
    const priorDate = format(subDays(new Date(d.date + 'T00:00:00'), 1), 'yyyy-MM-dd');
    const priorRow = biometricsSeries.find((s) => s?.date === priorDate);
    const v = priorRow ? Number((priorRow as any).strain_score) : NaN;
    return Number.isFinite(v) ? Math.round(v) : null;
  });

  const priorStrainBaseline = $derived.by(() => {
    if (!biometricsSeries?.length || !d?.date) return null;
    const priorDate = format(subDays(new Date(d.date + 'T00:00:00'), 1), 'yyyy-MM-dd');
    const vals = baselineWindowVals(biometricsSeries, priorDate, 'strain_score', 30);
    if (vals.length < 4) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  });

  const priorStrainDelta = $derived(
    isFiniteNumber(priorStrainScore) && isFiniteNumber(priorStrainBaseline)
      ? priorStrainScore - priorStrainBaseline
      : null
  );

  const sleepFillPct = $derived(sleepScoreToday === null ? 0 : Math.max(0, Math.min(100, sleepScoreToday)));
  const priorFillPct = $derived(priorStrainScore === null ? 0 : Math.max(0, Math.min(100, priorStrainScore)));

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

  let analysisText = $state<string | null>(null);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    void athleteStore.initialLoadDone;
    void athleteStore.loading;
    void d?.score;

    const day = d?.date;
    if (!day) {
      analysisText = null;
      return;
    }

    const cached = recoveryAnalysisMemo.get(day);
    if (cached !== undefined && cached !== null) {
      analysisText = cached;
      return;
    }

    analysisText = null;

    const requestKey = `recovery:${day}`;
    activeAnalysisKey = requestKey;

    (async () => {
      const res = await api.getRecoveryAnalysis(day);
      const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
      const next = content ? content : null;
      if (next) recoveryAnalysisMemo.set(day, next);

      if (activeAnalysisKey !== requestKey) return;
      analysisText = next;
    })();
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Daily Readiness</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Recovery</h1>
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
          onclick={() => (endPickerValue = format(subDays(windowEnd, 1), 'yyyy-MM-dd'))}
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
            endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd');
          }}
        >
          →
        </button>
      </div>
      <div class="text-[11px] text-text2 font-mono text-right">
        {rangeLabel}
      </div>
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
        <div class="flex items-center gap-4">
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
              <span class="text-[18px] font-bold">{quality}</span>
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

      <!-- Metrics Grid.
           HRV ms / RHR bpm are raw absolutes — value text stays neutral, the
           colored TrendIndicator next to the label carries the z-score signal
           (RHR is inverted: higher = worse). Sleep is a 0-100 score so the
           value itself is colored by the bounded-score rule. -->
      <div class="grid grid-cols-3 gap-2">
        <Card style="padding: 8px 10px;">
          <div class="flex items-start justify-between gap-1">
            <MetricBadge
              label="HRV"
              value={d.hrv}
              unit="ms"
              color={hrvZ === null ? 'var(--text2)' : zScoreCssColor(hrvZ)}
              sub="Avg"
            />
            <TrendIndicator z={hrvZ} size={14} />
          </div>
        </Card>
        <Card style="padding: 8px 10px;">
          <div class="flex items-start justify-between gap-1">
            <MetricBadge
              label="RHR"
              value={d.rhr}
              unit="bpm"
              color={rhrZ === null ? 'var(--text2)' : zScoreCssColor(rhrZ, true)}
              sub="Avg"
            />
            <TrendIndicator z={rhrZ} inverted size={14} />
          </div>
        </Card>
        <Card style="padding: 8px 10px;">
          <MetricBadge
            label="Sleep"
            value={d.sleepScore}
            unit="%"
            color={d.sleepScore ? boundedScoreCssColor(d.sleepScore) : 'var(--text2)'}
            sub="Score"
          />
        </Card>
      </div>

      <!-- 7-Day Trend -->
      <Card>
        <div class="flex justify-between items-center mb-3">
          <p class="text-[13px] font-semibold">7-Day Trend</p>
          <span class="text-[10px] text-text2 font-mono">
            avg {avg7d === null ? '--' : `${avg7d}%`} · {score}% current
          </span>
        </div>
        <div class="flex gap-2 items-end h-[50px] mb-1 px-1">
          {#each days as day, i (day.date)}
            {@const c = boundedScoreCssColor(day.score)}
            <button
              type="button"
              class="flex-1 flex flex-col items-center gap-1 cursor-pointer"
              onclick={() => {
                endPickerValue = day.date;
                dayIndex = 6;
              }}
              aria-label={`Select ${day.label}: ${day.score}/100`}
            >
              <div
                class="w-full rounded-t-sm transition-all duration-300"
                style="background: {c}; opacity: {i === dayIndex ? 1 : 0.35}; height: {Math.max(4, (day.score / 100) * 50)}px;"
              ></div>
              <span class="text-[9px] font-mono {i === dayIndex ? 'text-text0' : 'text-text2'}">{day.day}</span>
            </button>
          {/each}
        </div>
      </Card>
      
      <!-- Contributing Factors — split by behavior.
           Unbounded vitals (HRV, RHR, Body Temp, SpO2): raw absolute text is
             neutral (slate-200); the colored arrow + delta + center-anchored
             deviation dot carry the z-score signal. Track center == 7-day EWMA
             baseline, and the highlighted band marks the ±0.5 SD "normal
             range".
           Bounded scores (Sleep Quality, Prior Load): raw value text is
             neutral; the colored delta + left-to-right progress fill carry
             the rule-of-thirds signal applied to the underlying score
             (sleep score for Sleep Quality, prior-day strain score for
             Prior Load — strain is inverted, high strain == bad recovery
             contribution). -->
      <Card style="padding: 14px;">
        <div class="flex items-center justify-between mb-3">
          <p class="text-[13px] font-semibold">Contributing Factors</p>
          <span class="text-[10px] uppercase tracking-wider text-text1">vs baseline</span>
        </div>

        <div class="w-full space-y-0">
        <!-- ─── Vitals & Trends (unbounded, deviation tracks) ─── -->
        <p class="mb-3 text-[10px] uppercase tracking-wider text-text1">Vitals &amp; Trends</p>
        <div class="mb-6 flex w-full flex-col">
          <!-- HRV -->
          <div class="flex w-full flex-col gap-2 border-b border-white/[0.06] py-5">
            <!-- Top row: label + arrow | Δ + neutral absolute -->
            <div class="flex w-full items-center justify-between gap-4">
              <div class="min-w-0 flex items-center gap-1.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">HRV</p>
                <TrendIndicator z={hrvZ} size={12} />
              </div>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {hrvZ === null ? 'var(--text2)' : zScoreCssColor(hrvZ)}">
                  {formatSignedInt(hrvDelta)}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${hrvToday === null ? 'text-text2' : 'text-text0'}`}>
                  {hrvToday === null ? '--' : `${hrvToday}ms`}
                </span>
              </div>
            </div>
            <!-- Full-width track -->
            <div class="w-full">
              <DeviationTrack z={hrvZ} />
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {hrvToday === null
                ? 'Not available for this day.'
                : hrvBaseline === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : hrvDelta !== null && hrvDelta >= 0
                    ? `${Math.round(hrvDelta)}ms above your 7-day baseline of ${hrvBaseline}ms. Strong parasympathetic response.`
                    : `${Math.abs(Math.round(hrvDelta ?? 0))}ms below your 7-day baseline of ${hrvBaseline}ms. Lower HRV can reflect accumulated stress.`}
            </p>
          </div>

          <!-- Resting HR (inverted: higher == worse) -->
          <div class="flex w-full flex-col gap-2 border-b border-white/[0.06] py-5">
            <div class="flex w-full items-center justify-between gap-4">
              <div class="min-w-0 flex items-center gap-1.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">Resting HR</p>
                <TrendIndicator z={rhrZ} inverted size={12} />
              </div>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {rhrZ === null ? 'var(--text2)' : zScoreCssColor(rhrZ, true)}">
                  {formatSignedInt(rhrDelta)}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${rhrToday === null ? 'text-text2' : 'text-text0'}`}>
                  {rhrToday === null ? '--' : `${rhrToday}bpm`}
                </span>
              </div>
            </div>
            <div class="w-full">
              <DeviationTrack z={rhrZ} inverted />
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {rhrToday === null
                ? 'Not available for this day.'
                : rhrBaseline === null || rhrDelta === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : rhrDelta < 0
                    ? `${Math.abs(Math.round(rhrDelta))} bpm below your 7-day baseline of ${rhrBaseline}bpm. Low RHR indicates good cardiac efficiency.`
                    : `${Math.round(rhrDelta)} bpm above your 7-day baseline of ${rhrBaseline}bpm. Elevated RHR can reflect fatigue or stress.`}
            </p>
          </div>

          <!-- Body Temp (inverted: deviation higher == worse) -->
          <div class="flex w-full flex-col gap-2 border-b border-white/[0.06] py-5">
            <div class="flex w-full items-center justify-between gap-4">
              <div class="min-w-0 flex items-center gap-1.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">Body Temp</p>
                <TrendIndicator z={bodyTempZ} inverted size={12} />
              </div>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {bodyTempZ === null ? 'var(--text2)' : zScoreCssColor(bodyTempZ, true)}">
                  {bodyTempDeltaDisplay === null ? '--' : formatSigned1dp(bodyTempDeltaDisplay, isImperial ? '°F' : '°C')}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${bodyTempDisplay === null ? 'text-text2' : 'text-text0'}`}>
                  {bodyTempDisplay === null ? '--' : `${bodyTempDisplay}${isImperial ? '°F' : '°C'}`}
                </span>
              </div>
            </div>
            <div class="w-full">
              <DeviationTrack z={bodyTempZ} inverted />
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {bodyTempCToday === null
                ? 'Not available for this day.'
                : bodyTempBaselineDisplay === null || bodyTempDeltaDisplay === null
                  ? `Body temp recorded at ${bodyTempDisplay}${isImperial ? '°F' : '°C'}. Baseline not available yet.`
                  : Math.abs(bodyTempDeltaDisplay) > (isImperial ? 0.9 : 0.5)
                    ? `${formatSigned1dp(bodyTempDeltaDisplay, isImperial ? '°F' : '°C')} vs your 7-day baseline of ${bodyTempBaselineDisplay}${isImperial ? '°F' : '°C'}. Monitor for signs of illness or overheating.`
                    : `${formatSigned1dp(bodyTempDeltaDisplay, isImperial ? '°F' : '°C')} vs your 7-day baseline of ${bodyTempBaselineDisplay}${isImperial ? '°F' : '°C'}. Body temperature is stable.`}
            </p>
          </div>

          <!-- SpO2 -->
          <div class="flex w-full flex-col gap-2 border-b border-white/[0.06] py-5 last:border-b-0">
            <div class="flex w-full items-center justify-between gap-4">
              <div class="min-w-0 flex items-center gap-1.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">SpO2</p>
                <TrendIndicator z={spo2Z} size={12} />
              </div>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {spo2Z === null ? 'var(--text2)' : zScoreCssColor(spo2Z)}">
                  {formatSignedInt(spo2Delta)}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${spo2Pct === null ? 'text-text2' : 'text-text0'}`}>
                  {spo2Pct === null ? '--' : `${spo2Pct}%`}
                </span>
              </div>
            </div>
            <div class="w-full">
              <DeviationTrack z={spo2Z} />
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {spo2Pct === null
                ? 'Not available for this day.'
                : spo2Baseline === null || spo2Delta === null
                  ? 'Baseline not available yet. Keep syncing to build a 30-day trend.'
                  : spo2Pct < 94
                    ? 'Blood oxygen dipped below normal overnight. Consider sleep position, altitude, or congestion.'
                    : spo2Delta >= 0
                      ? `${Math.round(spo2Delta)}% above your 7-day baseline of ${spo2Baseline}%. Blood oxygen within normal range all night.`
                      : `${Math.abs(Math.round(spo2Delta))}% below your 7-day baseline of ${spo2Baseline}%. Blood oxygen slightly reduced overnight.`}
            </p>
          </div>
        </div>

        <!-- ─── Performance Drivers (bounded scores, progress bars) ─── -->
        <p class="mb-3 text-[10px] uppercase tracking-wider text-text1">Performance Drivers</p>
        <div class="flex w-full flex-col">
          <!-- Sleep Quality (rule of thirds, not inverted) -->
          <div class="flex w-full flex-col gap-2 border-b border-white/[0.06] py-5">
            <div class="flex w-full items-center justify-between gap-4">
              <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">Sleep Quality</p>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {sleepScoreToday === null ? 'var(--text2)' : boundedScoreCssColor(sleepScoreToday)}">
                  {formatSignedInt(sleepDelta)}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${sleepScoreToday === null ? 'text-text2' : 'text-text0'}`}>
                  {sleepScoreToday === null ? '--' : `${sleepScoreToday}%`}
                </span>
              </div>
            </div>
            <div class="h-[6px] w-full overflow-hidden rounded-full bg-bg2 ring-1 ring-inset ring-border">
              <div
                class="h-full rounded-full transition-[width] duration-300"
                style="width: {sleepFillPct}%; background: {sleepScoreToday === null ? 'var(--text2)' : boundedScoreCssColor(sleepScoreToday)};"
              ></div>
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {sleepScoreToday === null
                ? 'Not available for this day.'
                : `${sleepDurationHM === null ? '--' : sleepDurationHM} asleep with ${sleepScoreToday}% quality.${sleepDeepPct === null ? '' : ` Deep sleep at ${sleepDeepPct}%.`}`}
            </p>
          </div>

          <!-- Prior Load (strain score, INVERTED rule of thirds — high == bad) -->
          <div class="flex w-full flex-col gap-2 py-5">
            <div class="flex w-full items-center justify-between gap-4">
              <p class="text-[11px] font-semibold uppercase tracking-wide text-text0">Prior Load</p>
              <div class="shrink-0 flex items-baseline gap-2 leading-tight">
                <span class="text-[11px] font-mono tabular-nums" style="color: {priorStrainScore === null ? 'var(--text2)' : boundedScoreCssColor(priorStrainScore, true)}">
                  {formatSignedInt(priorStrainDelta)}
                </span>
                <span class={`text-[12px] font-semibold tabular-nums ${priorLoad?.dailyTss == null ? 'text-text2' : 'text-text0'}`}>
                  {priorLoad?.dailyTss == null ? '--' : `${priorLoad.dailyTss} TSS`}
                </span>
              </div>
            </div>
            <div class="h-[6px] w-full overflow-hidden rounded-full bg-bg2 ring-1 ring-inset ring-border">
              <div
                class="h-full rounded-full transition-[width] duration-300"
                style="width: {priorFillPct}%; background: {priorStrainScore === null ? 'var(--text2)' : boundedScoreCssColor(priorStrainScore, true)};"
              ></div>
            </div>
            <p class="text-[11px] leading-snug text-text1">
              {priorLoad === null
                ? 'Not available for this day.'
                : priorStrainScore === null
                  ? 'Yesterday’s strain score is not available yet.'
                  : priorStrainBaseline === null
                    ? `Yesterday's strain came in at ${priorStrainScore}/100. Baseline not available yet.`
                    : priorStrainDelta !== null && priorStrainDelta > 5
                      ? `Yesterday pushed strain ${priorStrainDelta} pts above your 30-day average. Expect some residual fatigue.`
                      : priorStrainDelta !== null && priorStrainDelta < -5
                        ? `Yesterday was a recovery day, ${Math.abs(priorStrainDelta)} pts below your 30-day strain average.`
                        : `Yesterday's strain (${priorStrainScore}/100) tracked your 30-day average.`}
            </p>
          </div>
        </div>
        </div>
      </Card>

      <!-- Analysis Card -->
      <Card
        class="!bg-gradient-to-br from-blue/10 via-transparent to-transparent"
      >
        <p class="text-[13px] font-semibold mb-1.5">Recovery Analysis</p>
        <p class="text-xs text-text1 leading-relaxed">
          {analysisText ??
            (score >= 67
              ? 'Your recovery architecture looks balanced. Systemic fatigue is low.'
              : score >= 34
                ? 'Your autonomic system is recovering. Focus on maintaining parasympathetic tone.'
                : 'High systemic load detected. Prioritize high-quality sleep to accelerate repair.')}
        </p>
      </Card>
    {/if}

    <!-- Timeline -->
  {/if}
</div>
