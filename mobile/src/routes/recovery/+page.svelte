<script module lang="ts">

</script>

<script lang="ts">
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import BaselineBar from '$lib/components/BaselineBar.svelte';
  import DashedNote from '$lib/components/ui/DashedNote.svelte';
  import { goto } from '$app/navigation';
  import { boundedScoreCssColor, zScoreCssColor } from '$lib/scoreColors';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { normalizeUnits, type Units } from '$lib/utils/units';
  import { currentRecoveryState, firstPositiveFiniteNumber } from '$lib/utils/biometrics';
  import { onMount } from 'svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { bodyDate, rememberBodyDate } from '$lib/stores/bodyDate.svelte';
  import { addDays, format, subDays } from 'date-fns';
  import { page } from '$app/stores';
  import { viewport } from '$lib/stores/viewport.svelte';
  import { bodyEyebrow } from '$lib/utils/bodyWide';
  import BodyScoreTabs from '$lib/components/wide/body/BodyScoreTabs.svelte';
  import RecoveryWide from '$lib/components/wide/body/RecoveryWide.svelte';

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

  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state(bodyDate.value ?? format(new Date(), 'yyyy-MM-dd')); // YYYY-MM-DD
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
  const canGoForward = $derived(format(windowEnd, 'yyyy-MM-dd') !== todayStr);

  $effect(() => {
    pageHeader.prev = () => { endPickerValue = format(subDays(windowEnd, 1), 'yyyy-MM-dd'); dayIndex = 6; };
    pageHeader.next = () => { if (canGoForward) { endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd'); dayIndex = 6; } };
    pageHeader.canNext = canGoForward;
    pageHeader.today = () => { endPickerValue = todayStr; dayIndex = 6; };
    pageHeader.dateMax = todayStr;
    pageHeader.dateLabel = canGoForward ? format(clampedEndDay, 'EEE d MMM') : 'Today';
    pageHeader.dateMarks = (athleteStore.biometrics?.series ?? []).filter((r: any) => r?.date && Number(r?.recovery_score) > 0).map((r: any) => r.date);
    pageHeader.dateValue = format(clampedEndDay, "yyyy-MM-dd");
    // Wide layouts show Recovery, Sleep and Strain as one "Body" screen.
    pageHeader.wideTitle = 'Body';
    pageHeader.wideEyebrow = bodyEyebrow(days[dayIndex]?.date ?? todayStr, days[dayIndex]?.data ?? (current.row as any));
    return resetPageHeader;
  });

  // Share the picked day with the other Body sub-tabs (Recovery / Sleep / Strain).
  $effect(() => {
    rememberBodyDate(format(addDays(windowStart, dayIndex), 'yyyy-MM-dd'), todayStr);
  });

  // The header calendar writes pageHeader.dateValue; follow it.
  $effect(() => {
    const picked = pageHeader.dateValue;
    if (picked && picked !== endPickerValue && picked <= todayStr) { endPickerValue = picked; dayIndex = 6; }
  });

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
  const current = $derived(
    currentRecoveryState(
      athleteStore.biometrics?.series,
      athleteStore.profile?.timezone_offset_min
    )
  );

  const useHeadlineCarryForward = $derived(
    d?.date === todayStr &&
      (d.missing || !Number.isFinite(Number(d?.data?.recovery_score)))
  );

  const headlineRow = $derived(
    useHeadlineCarryForward && current.row ? current.row : (d?.data ?? null)
  );

  const showRecoveryHero = $derived(!d.missing || (useHeadlineCarryForward && current.row != null));

  const carryOverLabel = $derived.by(() => {
    if (!useHeadlineCarryForward || !current.row || current.hasTodayRow) return null;
    if (current.ageHours !== null && current.ageHours < 36) return 'Carried over from last night';
    if (current.date) {
      try {
        return `Carried over from ${format(new Date(current.date + 'T12:00:00'), 'MMM d')}`;
      } catch {
        return 'Carried over from previous night';
      }
    }
    return 'Carried over from previous night';
  });

  const hasData = $derived(
    days.some((day) => !day.missing) || current.row != null || athleteStore.readiness > 0
  );
  // "Connect an app" only when we *know* nothing is connected and there's no data:
  // manual-only athletes (logged sleep/workouts) see their data, and connected users
  // don't flash this while the sync status is still loading.
  const showConnectPrompt = $derived(athleteStore.syncStatus != null && !isConnected && !hasData);
  /** Recovery needs an overnight wearable; Strava/Intervals alone never produce it. */
  const hasRecoveryWearable = $derived.by(() => {
    const i = athleteStore.syncStatus?.integrations ?? {};
    return !!(i.whoop?.connected || i.garmin?.connected);
  });
  const showRecoverySetup = $derived(athleteStore.syncStatus != null && !hasRecoveryWearable && !hasData);

  let checking = $state(false);
  async function checkSync() {
    checking = true;
    try {
      await athleteStore.fetchAll(true);
    } finally {
      checking = false;
    }
  }

  // Recovery only: readiness mixes in training form, so it isn't a recovery score.
  // The hero only renders when headlineRow carries a recovery_score.
  const score = $derived(firstPositiveFiniteNumber(headlineRow?.recovery_score) ?? 0);
  const scoreColor = $derived(
    current.isStale && d?.date === todayStr
      ? 'var(--text2)'
      : boundedScoreCssColor(score)
  );
  const quality = $derived(score >= 67 ? 'Optimal' : score >= 34 ? 'Moderate' : 'Fatigued');

  const hrvZ = $derived(
    typeof headlineRow?.hrv_z === 'number' && Number.isFinite(headlineRow.hrv_z)
      ? Number(headlineRow.hrv_z)
      : null
  );
  const rhrZ = $derived(
    typeof headlineRow?.rhr_z === 'number' && Number.isFinite(headlineRow.rhr_z)
      ? Number(headlineRow.rhr_z)
      : null
  );

  const units = $derived<Units>(normalizeUnits((athleteStore.profile as any)?.measurement_units));
  const isImperial = $derived(units === 'imperial');
  
  const biometricsSeries = $derived(athleteStore.biometrics?.series as BiometricsRecord[] | undefined);
  
  const hrvToday = $derived(
    isFiniteNumber(headlineRow?.hrv_rmssd) ? Math.round(Number(headlineRow.hrv_rmssd)) : null
  );
  const hrvDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'hrv_rmssd', hrvToday, 7));

  const rhrToday = $derived(
    isFiniteNumber(headlineRow?.resting_hr) ? Math.round(Number(headlineRow.resting_hr)) : null
  );
  const rhrDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'resting_hr', rhrToday, 7));

  const sleepScoreToday = $derived(
    isFiniteNumber(headlineRow?.sleep_score) ? Math.round(Number(headlineRow.sleep_score)) : null
  );
  const sleepDelta = $derived(signedDeltaVsBaseline(biometricsSeries, d.date, 'sleep_score', sleepScoreToday, 7));
  
  // NOTE: `skin_temp` stores *skin/body temperature in °C*.
  // We treat it as an actual temperature measurement and show deviation vs baseline.
  const bodyTempCToday = $derived(
    isFiniteNumber(headlineRow?.skin_temp) ? Number(headlineRow.skin_temp) : null
  );
  const bodyTempCBaseline = $derived.by(() => {
    const base = baselineAvg7d(biometricsSeries, d.date, 'skin_temp');
    if (!isFiniteNumber(base)) return null;
    return Math.round(base * 10) / 10;
  });
  // Garmin reports skin temp only as a deviation from the athlete's own baseline
  // (`skin_temp_deviation_c`), never an absolute reading, so prefer it when present.
  const bodyTempCDelta = $derived.by(() => {
    const deviation = Number(headlineRow?.skin_temp_deviation_c);
    if (headlineRow?.skin_temp_deviation_c != null && Number.isFinite(deviation)) return deviation;
    if (!isFiniteNumber(bodyTempCToday) || !isFiniteNumber(bodyTempCBaseline)) return null;
    return bodyTempCToday - bodyTempCBaseline;
  });

  const bodyTempDeltaDisplay = $derived.by(() => {
    if (!isFiniteNumber(bodyTempCDelta)) return null;
    const val = isImperial ? deltaCToF(bodyTempCDelta) : bodyTempCDelta;
    return Math.round(val * 10) / 10;
  });

  const spo2Pct = $derived(
    isFiniteNumber(headlineRow?.spo2_pct) ? Math.round(Number(headlineRow.spo2_pct)) : null
  );

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

  // (An AI analysis used to be requested here on every day change and never shown,
  // costing an LLM generation per view. Removed; the dashboard summary covers it.)
</script>

{#if viewport.wide && !(showConnectPrompt || showRecoverySetup) && hasData}
  <div class="flex-1 flex flex-col gap-[22px]">
    <BodyScoreTabs active="recovery" day={d.date} />
    <RecoveryWide
      series={biometricsSeries ?? []}
      day={d.date}
      row={showRecoveryHero ? headlineRow : null}
      {days}
      selected={dayIndex}
      onSelect={(i) => (dayIndex = i)}
      {isImperial}
    />
  </div>
{:else}
<div class="flex flex-col gap-3.5">
  {#if showConnectPrompt || showRecoverySetup}
    <EmptyStateCard
      icon="link"
      tone="blue"
      eyebrow="Not set up"
      title="Connect a recovery wearable"
      message="Recovery is built from your overnight HRV, resting heart rate and sleep. WHOOP or a Garmin watch worn to bed both work."
      actionLabel="Connect WHOOP"
      onAction={() => goto('/profile/connections')}
      secondaryLabel="Connect Garmin"
      onSecondary={() => goto('/profile/connections')}
    />
    <DashedNote label="Meanwhile" layout="inline">
      Strain still works from your workouts, and training load — fitness, fatigue and form — doesn't need a wearable.
    </DashedNote>
  {:else if !hasData}
    <EmptyStateCard
      icon="refresh"
      tone="amber"
      eyebrow="Waiting for sync"
      title="No recovery yet"
      message="Your wearable is connected. Recovery appears after your first night of sleep syncs, usually within 30 minutes of waking."
      actionLabel={checking ? 'Checking…' : 'Check sync now'}
      onAction={checkSync}
    />
  {:else if !showRecoveryHero}
    <EmptyStateCard
      icon="refresh"
      tone="amber"
      eyebrow="Waiting for sync"
      title="No recovery for {d.label}"
      message="There's no overnight HRV or resting heart rate for this day yet. Your watch may not have synced, or it wasn't worn that night."
      actionLabel={checking ? 'Checking…' : 'Check sync now'}
      onAction={checkSync}
    />
  {:else}
    <!-- Score -->
    <section aria-label="Recovery score" class="bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex gap-[18px] items-center">
      <div class="relative w-[112px] h-[112px] shrink-0">
        <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true" class="block -rotate-90">
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--border)" stroke-width="8"></circle>
          <circle cx="56" cy="56" r="48" fill="none" stroke={scoreColor} stroke-width="8" stroke-linecap="round" stroke-dasharray="{(Math.min(score, 100) / 100) * 301.6} 302"></circle>
        </svg>
        <div class="absolute inset-0 flex items-center justify-center">
          <span class="font-display text-[42px] leading-none">{Math.round(score)}<span class="text-[20px]">%</span></span>
        </div>
      </div>
      <div class="flex flex-col gap-1.5">
        <span class="font-mono text-[11px] tracking-[0.14em] uppercase" style="color: {scoreColor}">{score >= 67 ? 'Recovered' : score >= 34 ? 'Moderate' : 'Fatigued'}</span>
        <p class="m-0 text-sm leading-[1.45] text-text1">
          {score >= 67 ? 'Your nervous system is well-rested and primed for quality effort.'
            : score >= 34 ? 'Moderate physiological state. Listen to your body during training.'
            : 'Significant fatigue detected. Prioritize sleep and active recovery today.'}
        </p>
        {#if carryOverLabel}<span class="font-mono text-[11px] text-text2">{carryOverLabel}</span>{/if}
        {#if spo2Pct !== null || bodyTempDeltaDisplay !== null}
          <span class="font-mono text-[11px] text-text2">
            {#if spo2Pct !== null}SpO2 {spo2Pct}%{/if}{#if spo2Pct !== null && bodyTempDeltaDisplay !== null} · {/if}{#if bodyTempDeltaDisplay !== null}Skin {formatSigned1dp(bodyTempDeltaDisplay, '°')}{/if}
          </span>
        {/if}
      </div>
    </section>

    <!-- Contributing factors -->
    <section aria-label="Contributing factors" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-1">
      <div class="flex justify-between items-baseline pb-1.5">
        <h2 class="m-0 font-display font-normal text-[22px]">vs your baseline</h2>
        <span class="font-mono text-[11px] text-text2">7-DAY</span>
      </div>
      {#each [
        { name: 'HRV', val: hrvToday === null ? '--' : `${hrvToday} ms`, delta: formatSignedInt(hrvDelta), z: hrvZ, inverted: false },
        { name: 'Resting HR', val: rhrToday === null ? '--' : `${rhrToday} bpm`, delta: formatSignedInt(rhrDelta), z: rhrZ, inverted: true },
        { name: 'Sleep', val: sleepScoreToday === null ? '--' : `${sleepScoreToday}%`, delta: formatSignedInt(sleepDelta), z: sleepDelta === null ? null : sleepDelta / 8, inverted: false }
      ] as f (f.name)}
        <BaselineBar name={f.name} value={f.val} delta={f.delta} z={f.z} color={f.z === null ? 'var(--text2)' : zScoreCssColor(f.z, f.inverted)} />
      {/each}
    </section>

    <!-- 7-day trend -->
    <section aria-label="7-day trend" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-2.5">
      <h2 class="m-0 font-display font-normal text-[22px]">7-day trend</h2>
      <div class="grid grid-cols-7 gap-2 items-end h-[70px]">
        {#each days as day, i (day.date)}
          <!-- The whole column is the tap target (a 4px bar was too small to hit). -->
          <button
            type="button"
            aria-label={day.missing ? `Select ${day.label}: no recovery score` : `Select ${day.label}: ${day.score}/100`}
            aria-pressed={i === dayIndex}
            class="flex items-end h-full p-0 border-0 bg-transparent cursor-pointer"
            onclick={() => { endPickerValue = day.date; dayIndex = 6; }}
          >
            <span
              aria-hidden="true"
              class="block w-full rounded-md"
              style="height: {Math.max(4, Math.round(day.score * 0.7))}px; background: {boundedScoreCssColor(day.score)}; opacity: {i === dayIndex ? 1 : 0.45}"
            ></span>
          </button>
        {/each}
      </div>
      <div class="grid grid-cols-7 gap-2 text-center font-mono text-[10px] text-text2">
        {#each days as day, i (day.date)}
          <span class={i === dayIndex ? 'text-text0' : ''}>{day.day}</span>
        {/each}
      </div>
    </section>
  {/if}
</div>
{/if}
