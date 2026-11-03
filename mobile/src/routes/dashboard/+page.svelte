<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';
  import { stripLeadingTimeOfDayGreeting } from '$lib/utils/greeting';

  const AI_SUMMARY_CACHE_KEY = 'astraphe:dashboard-ai-summary:v3';

  function _sanitizeAiSummary(content: string) {
    return stripLeadingTimeOfDayGreeting(content);
  }

  function _loadAiSummaryCache(): Record<string, string> {
    if (typeof localStorage === 'undefined') return {};
    try {
      const raw = localStorage.getItem(AI_SUMMARY_CACHE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return {};
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(parsed)) {
        if (typeof v === 'string') {
          const summary = _sanitizeAiSummary(v);
          if (summary) out[k] = summary;
        }
      }
      return out;
    } catch {
      return {};
    }
  }

  function _persistAiSummary(day: string, content: string) {
    if (typeof localStorage === 'undefined') return;
    try {
      const current = _loadAiSummaryCache();
      const summary = _sanitizeAiSummary(content);
      if (!summary) return;
      current[day] = summary;
      // Keep only the last 14 days to bound size.
      const keys = Object.keys(current).sort();
      while (keys.length > 14) delete current[keys.shift()!];
      localStorage.setItem(AI_SUMMARY_CACHE_KEY, JSON.stringify(current));
    } catch {
      // ignore quota errors
    }
  }

  const dashboardAiSummaryMemo = new SvelteMap<string, string | null>(
    Object.entries(_loadAiSummaryCache())
  );
</script>

<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import TrendBars from '$lib/components/charts/TrendBars.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import CalibrationBadge from '$lib/components/CalibrationBadge.svelte';
  import { onMount } from 'svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { format } from 'date-fns';
  import type { Workout } from '$lib/types/training';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import { CHART_ATL_STROKE, CHART_CTL_STROKE, formCssColor } from '$lib/scoreColors';
  import { getTimeOfDayGreeting } from '$lib/utils/greeting';
  import { currentRecoveryState, firstPositiveFiniteNumber, readinessScoreFromRow } from '$lib/utils/biometrics';

  const CTL_IDENTITY_HEX = CHART_CTL_STROKE;
  const ATL_IDENTITY_HEX = CHART_ATL_STROKE;

  const props = $props();

  let greetingNow = $state(new Date());
  const currentDateLabel = $derived(format(greetingNow, 'EEEE, MMM d'));
  const currentGreeting = $derived(getTimeOfDayGreeting(greetingNow));

  onMount(() => {
    athleteStore.fetchAll();
    greetingNow = new Date();
    const greetingTimer = window.setInterval(() => {
      greetingNow = new Date();
    }, 60_000);

    return () => window.clearInterval(greetingTimer);
  });

  const isCalibrating = $derived(
    athleteStore.initialLoadDone &&
    athleteStore.days_on_platform > 0 &&
    athleteStore.days_on_platform < 42
  );
  // --- Key session (today's planned workout) ---
  const ZONE_LABEL: Record<string, string> = {
    Recovery: 'Z1',
    Endurance: 'Z2',
    Tempo: 'Z3–Z4',
    Threshold: 'Z4',
    VO2Max: 'Z5',
    Anaerobic: 'Z6'
  };
  let plannedWorkouts = $state<Workout[]>([]);
  const todayIso = $derived(format(greetingNow, 'yyyy-MM-dd'));

  onMount(async () => {
    const iso = format(new Date(), 'yyyy-MM-dd');
    plannedWorkouts = await api.getWorkouts(iso, iso);
  });

  const keySession = $derived(plannedWorkouts.find((w) => w.date === todayIso) ?? null);
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);
  const sessionRange = $derived.by(() => {
    const w = keySession;
    if (!w) return null;
    const round5 = (n: number) => Math.round(n / 5) * 5;
    const duration = `${round5(w.duration_minutes * 0.95)}–${round5(w.duration_minutes * 1.05)}`;
    const work = (w.structure ?? []).reduce<number>(
      (max, i) => Math.max(max, i.target_power_percent_ftp ?? 0),
      0
    );
    if (w.sport === 'bike' && ftp > 0 && work > 0) {
      return {
        duration,
        valueLabel: `${Math.round((ftp * work) / 100)}–${Math.round((ftp * (work + 5)) / 100)}`,
        unit: 'W',
        caption: `Target · ${work}–${work + 5}% FTP`
      };
    }
    return { duration, valueLabel: String(w.projected_tss), unit: 'TSS', caption: 'Projected load' };
  });
  /** One bar per interval, width ∝ duration, tall + accent when it is hard work. */
  const profileBars = $derived(
    (keySession?.structure ?? []).map((i) => {
      const hard = (i.target_power_percent_ftp ?? 0) >= 85 || (i.target_hr_zone ?? 0) >= 4;
      return { grow: Math.max(i.duration_minutes, 1), hard, name: i.name };
    })
  );

  const hasData = $derived(athleteStore.workouts?.length > 0 || athleteStore.readiness > 0);
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));

  const todayStr = $derived(format(new Date(), 'yyyy-MM-dd'));
  const isoDate = (v: unknown) => (typeof v === 'string' ? v.slice(0, 10) : '');

  const todayLoad = $derived(athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === todayStr));
  const latestLoad = $derived(
    athleteStore.metrics?.trainingLoadData?.[athleteStore.metrics.trainingLoadData.length - 1]
  );

  const current = $derived(
    currentRecoveryState(
      athleteStore.biometrics?.series,
      athleteStore.profile?.timezone_offset_min
    )
  );

  const currentRow = $derived(current.row);

  const todayReadiness = $derived(readinessScoreFromRow(currentRow));
  const todayRecoveryScore = $derived(
    firstPositiveFiniteNumber(currentRow?.recovery_score, currentRow?.readiness_score)
  );
  const latestHrv = $derived(
    typeof currentRow?.hrv_rmssd === 'number' && Number.isFinite(currentRow.hrv_rmssd)
      ? currentRow.hrv_rmssd
      : null
  );
  const latestSleepMin = $derived(
    typeof currentRow?.sleep_duration_min === 'number' && Number.isFinite(currentRow.sleep_duration_min)
      ? currentRow.sleep_duration_min
      : null
  );
  const latestSleepScore = $derived(
    typeof currentRow?.sleep_score === 'number' && Number.isFinite(currentRow.sleep_score)
      ? currentRow.sleep_score
      : null
  );
  const latestHrvZ = $derived(
    typeof currentRow?.hrv_z === 'number' && Number.isFinite(currentRow.hrv_z) ? Number(currentRow.hrv_z) : null
  );

  const carryOverLabel = $derived.by(() => {
    if (!current.row || current.hasTodayRow) return null;
    if (current.ageHours !== null && current.ageHours < 36) return 'Carried over from last night';
    if (current.date) {
      try {
        return `Carried over from ${format(new Date(current.date + 'T12:00:00'), 'MMM d')}`;
      } catch {
        return null;
      }
    }
    return null;
  });

  const todayCtl = $derived(todayLoad?.ctl ?? latestLoad?.ctl ?? null);
  const todayAtl = $derived(todayLoad?.atl ?? latestLoad?.atl ?? null);
  const todayTsb = $derived(todayLoad?.tsb ?? latestLoad?.tsb ?? null);

  function isFiniteNumber(v: unknown): v is number {
    return typeof v === 'number' && Number.isFinite(v);
  }

  let analysisText = $state<string | null>(null);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    void athleteStore.initialLoadDone;
    void athleteStore.loading;

    const endDay = todayStr;

    const cached = dashboardAiSummaryMemo.get(endDay);
    if (cached !== undefined && cached !== null) {
      const summary = _sanitizeAiSummary(cached);
      if (summary) {
        if (summary !== cached) {
          dashboardAiSummaryMemo.set(endDay, summary);
          _persistAiSummary(endDay, summary);
        }
        analysisText = summary;
      } else {
        dashboardAiSummaryMemo.delete(endDay);
      }
    } else if (cached === null) {
      dashboardAiSummaryMemo.delete(endDay);
    }

    const requestKey = `dashboard-ai-summary:${endDay}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        const res = await api.getDashboardSummary(endDay);
        const content = typeof res?.analysis?.content === 'string'
          ? _sanitizeAiSummary(res.analysis.content)
          : '';
        const next = content ? content : null;
        const analysis = res?.analysis;
        const isProvisional =
          analysis?.fallback === true || analysis?.stale === true;
        if (next && !isProvisional) {
          dashboardAiSummaryMemo.set(endDay, next);
          _persistAiSummary(endDay, next);
        }

        if (activeAnalysisKey !== requestKey) return;
        if (next) analysisText = next;
      } catch (e) {
        console.error(e);
        if (activeAnalysisKey !== requestKey) return;
        // Keep placeholder text while loading/failing.
      }
    })();
  });

  const fallbackSummary = $derived.by(() => {
    const tsb = isFiniteNumber(todayTsb) ? todayTsb : null;
    const ctl = isFiniteNumber(todayCtl) ? todayCtl : null;
    const atl = isFiniteNumber(todayAtl) ? todayAtl : null;

    if (tsb !== null) {
      if (tsb > 10) return `You look fresh today (TSB +${Math.round(tsb)}). Consider a quality session or a performance-focused workout.`;
      if (tsb < -20) return `You’re carrying high fatigue (TSB ${Math.round(tsb)}). Prioritize recovery or keep intensity low today.`;
      return `Your training balance looks steady (TSB ${tsb > 0 ? '+' : ''}${Math.round(tsb)}). Stay consistent with your planned progression.`;
    }

    if (ctl !== null && atl !== null) {
      const delta = atl - ctl;
      if (delta > 10) return `Your short-term load is above your baseline (ATL > CTL). Consider dialing back intensity if you feel run-down.`;
      if (delta < -10) return `Your short-term load is below your baseline (ATL < CTL). You may be ready to build back up if recovery is good.`;
      return `Your load looks balanced (ATL ~ CTL). Maintain a steady rhythm and adjust based on how you feel.`;
    }

    return 'Your training summary will appear once today’s load metrics finish syncing.';
  });

  const sleepHM = (mins: number | null) => {
    if (mins === null || mins === undefined) return 'Data not found';
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    const r = m % 60;
    return `${h}h ${r}m`;
  };

  // Bounded scores (Recovery, Sleep) follow the unified rule of thirds —
  // see scoreColors.ts. Local hex literals were removed so the rule lives in
  // exactly one place across the app.
  const recoveryColor = (score: number) => boundedScoreCssColor(score);
  const sleepColor = (score: number | null) => boundedScoreCssColor(score);
  const formatSleepHours = (hrsRaw: any) => {
    const hrs = typeof hrsRaw === 'number' ? hrsRaw : Number(hrsRaw);
    if (!Number.isFinite(hrs)) return 'Data not found';
    const mins = Math.round(hrs * 60);
    return sleepHM(mins);
  };

  const avg = (vals: number[]) => {
    const clean = vals.filter((v) => Number.isFinite(v));
    if (clean.length === 0) return null;
    return clean.reduce((a, b) => a + b, 0) / clean.length;
  };

  const avgHrv7d = $derived.by(() => {
    const src = (athleteStore.biometrics?.hrvData || []).slice(-7);
    const a = avg(src.map((v: unknown) => Number(v)).filter((v: number) => v > 0));
    return a === null ? null : Math.round(a);
  });

  const recoveryTrend = $derived.by(() => {
    const series = athleteStore.biometrics?.series || [];
    return series.slice(-28).map((s: any) => {
      const v = firstPositiveFiniteNumber(s?.recovery_score, s?.readiness_score);
      return {
        date: typeof s?.date === 'string' ? s.date : '',
        value: v
      };
    });
  });

  const recoveryTrendData = $derived(recoveryTrend.map((p: any) => p.value));
  const recoveryTrendKeys = $derived(recoveryTrend.map((p: any) => p.date));
  const recoveryTrendLabels = $derived(
    recoveryTrend.map((p: any) => {
      if (!p?.date) return '';
      const d = new Date(p.date + 'T00:00:00');
      return Number.isNaN(d.getTime()) ? String(p.date) : format(d, 'MMM d');
    })
  );

  const avgRecovery7d = $derived.by(() => {
    const src = recoveryTrendData.slice(-7);
    const a = avg(src);
    return a === null ? null : Math.round(a);
  });

  const avgSleep7dMin = $derived.by(() => {
    const src = (athleteStore.biometrics?.sleepData || []).slice(-7); // hours (float)
    const a = avg(src.map((v: unknown) => Number(v)).filter((v: number) => v > 0));
    return a === null ? null : Math.round(a * 60);
  });

  const sleepTrend = $derived.by(() => {
    const series = athleteStore.biometrics?.series || [];
    return series.slice(-28).map((s: any) => {
      const v = Number(s?.sleep_score);
      return {
        date: typeof s?.date === 'string' ? s.date : '',
        value: Number.isFinite(v) && v > 0 ? v : null
      };
    });
  });

  const sleepTrendData = $derived(sleepTrend.map((p: any) => p.value));
  const sleepTrendKeys = $derived(sleepTrend.map((p: any) => p.date));
  const sleepTrendLabels = $derived(
    sleepTrend.map((p: any) => {
      if (!p?.date) return '';
      const d = new Date(p.date + 'T00:00:00');
      return Number.isNaN(d.getTime()) ? String(p.date) : format(d, 'MMM d');
    })
  );

  const avgSleepScore7d = $derived.by(() => {
    const vals = sleepTrendData.slice(-7).map((x: any) => Number(x)).filter((v: number) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return Math.round(vals.reduce((a: number, b: number) => a + b, 0) / vals.length);
  });
</script>

<div class="flex flex-col gap-3">
  <!-- Header (Visible on Desktop, as Mobile has layout header) -->
  <div class="hidden md:flex justify-between items-start">
    <div>
      <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">{currentDateLabel}</p>
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">{currentGreeting}, {authStore.user?.user_metadata?.full_name || 'Athlete'}</h1>
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

    <!-- Key session -->
    {#if keySession && sessionRange}
      <a
        href={resolve(`/plan?session=${encodeURIComponent(keySession.id)}`)}
        aria-label="Open {keySession.title} in your plan"
        class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-3.5 text-text0"
      >
        <div class="flex justify-between items-center">
          <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">Key session · {keySession.sport}</span>
          <span class="flex items-center gap-1 font-mono text-[11px] text-text2">
            {ZONE_LABEL[keySession.primary_zone] ?? ''}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
          </span>
        </div>
        <div class="flex flex-col gap-1">
          <h2 class="m-0 font-display font-normal text-[34px] leading-[1.05]">{keySession.title}</h2>
          {#if keySession.description}
            <p class="m-0 text-sm leading-[1.45] text-text1">{keySession.description}</p>
          {/if}
        </div>
        <div class="grid grid-cols-2 gap-3 border-t border-border">
          <div class="flex flex-col gap-0.5 pt-2.5">
            <span class="text-[26px] font-medium tracking-[-0.02em]">{sessionRange.duration}<span class="text-[13px] text-text2 font-normal"> min</span></span>
            <span class="text-xs text-text2">Duration</span>
          </div>
          <div class="flex flex-col gap-0.5 pt-2.5">
            <span class="text-[26px] font-medium tracking-[-0.02em]">{sessionRange.valueLabel}<span class="text-[13px] text-text2 font-normal"> {sessionRange.unit}</span></span>
            <span class="text-xs text-text2">{sessionRange.caption}</span>
          </div>
        </div>
        {#if profileBars.length > 0}
          <div role="img" aria-label="Workout profile" class="flex items-end gap-[3px] h-16">
            {#each profileBars as b, idx (idx)}
              <div
                class="rounded-[3px] {b.hard ? 'bg-blue h-14' : 'bg-text2/40 h-5'}"
                style="flex: {b.grow} 1 0"
              ></div>
            {/each}
          </div>
        {/if}
      </a>
    {:else}
      <section aria-label="Key session" class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-3.5">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">NO SESSION PLANNED</span>
        <h2 class="m-0 font-display font-normal text-[34px] leading-[1.05]">Rest day</h2>
        <p class="m-0 text-sm leading-[1.45] text-text1">Nothing on the plan. Ask your coach if you want to add something.</p>
      </section>
    {/if}

    <!-- Readiness Card -->
    <Card class="!bg-bg2 !p-0">
      <a
        href={resolve('/readiness')}
        class="block w-full text-left px-5 py-[18px] text-text0"
        aria-label="Readiness details"
      >
        <div class="flex items-center gap-[18px]">
          <div class="flex flex-col gap-0.5 min-w-[92px]">
            <span class="font-mono text-[11px] tracking-[0.14em] text-text2">READINESS</span>
            <span
              class="font-display text-[56px] leading-none"
              style="color: {todayReadiness === null || current.isStale ? 'var(--text2)' : 'var(--text0)'}"
            >{todayReadiness === null ? '--' : todayReadiness}</span>
            {#if todayReadiness === null}
              <span class="text-xs text-text2">No data</span>
            {:else if todayReadiness >= 67}
              <span class="text-xs text-green">Good to train</span>
            {:else if todayReadiness >= 34}
              <span class="text-xs text-amber">Moderate</span>
            {:else}
              <span class="text-xs text-red">Recovery day</span>
            {/if}
          </div>
          <dl class="m-0 flex-1 grid grid-cols-2 gap-x-3 gap-y-2.5">
            <div>
              <dt class="text-[11px] text-text2">Recovery</dt>
              <dd class="m-0 text-[15px] font-medium">{todayRecoveryScore === null ? '--' : `${Math.round(Number(todayRecoveryScore))}%`}</dd>
            </div>
            <div>
              <dt class="text-[11px] text-text2">HRV</dt>
              <dd class="m-0 text-[15px] font-medium">{latestHrv === null ? '--' : `${Math.round(latestHrv)} ms`}</dd>
            </div>
            <div>
              <dt class="text-[11px] text-text2">Sleep</dt>
              <dd class="m-0 text-[15px] font-medium">{latestSleepMin === null ? '--' : sleepHM(latestSleepMin)}</dd>
            </div>
            <div>
              <dt class="text-[11px] text-text2">Form</dt>
              <dd class="m-0 text-[15px] font-medium">{todayTsb === null ? '--' : (todayTsb > 0 ? `+${todayTsb.toFixed(1)}` : todayTsb.toFixed(1))}</dd>
            </div>
          </dl>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="shrink-0 text-text2"><path d="m9 6 6 6-6 6"></path></svg>
        </div>
        {#if isCalibrating || carryOverLabel || current.isStale}
          <div class="flex flex-wrap items-center gap-2 mt-3 text-[10px] text-text2 font-mono">
            {#if isCalibrating}<CalibrationBadge />{/if}
            {#if carryOverLabel}<span>{carryOverLabel}</span>{/if}
            {#if current.isStale}
              <span>Last synced {current.ageHours != null ? Math.round(current.ageHours) : '—'}h ago — sync your device</span>
            {/if}
          </div>
        {/if}
      </a>
    </Card>

    <!-- AI Summary -->
    <a href={resolve('/chat')} class="flex items-start gap-3 px-[18px] py-4 rounded-[20px] bg-bg1 border border-dashed border-border">
      <span aria-hidden="true" class="shrink-0 w-7 h-7 rounded-full bg-blue-dim text-blue flex items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 18c3-8 13-8 16 0"></path><path d="M8 18c1.5-4 6.5-4 8 0"></path></svg>
      </span>
      <span class="text-[13px] leading-[1.45] text-text1">{analysisText ?? fallbackSummary}</span>
    </a>
  {/if}
</div>


