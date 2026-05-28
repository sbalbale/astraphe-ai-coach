<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';
  import { stripLeadingTimeOfDayGreeting } from '$lib/utils/greeting';

  const AI_SUMMARY_CACHE_KEY = 'astraphe:dashboard-ai-summary:v2';

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
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import TrendBars from '$lib/components/charts/TrendBars.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import CalibrationBadge from '$lib/components/CalibrationBadge.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { onMount } from 'svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { format } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/colorSystem';
  import { CHART_ATL_STROKE, CHART_CTL_STROKE, formCssColor, getZScoreColor } from '$lib/scoreColors';
  import { getTimeOfDayGreeting } from '$lib/utils/greeting';

  const CTL_IDENTITY_HEX = CHART_CTL_STROKE;
  const ATL_IDENTITY_HEX = CHART_ATL_STROKE;

  const props = $props();

  let showReadinessModal = $state(false);
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
  const hasData = $derived(athleteStore.workouts?.length > 0 || athleteStore.readiness > 0);
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));

  const todayStr = $derived(format(new Date(), 'yyyy-MM-dd'));
  const isoDate = (v: unknown) => (typeof v === 'string' ? v.slice(0, 10) : '');

  const todayBio = $derived(athleteStore.biometrics?.series?.find((s: any) => s.date === todayStr));
  const todayLoad = $derived(athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === todayStr));
  const latestBio = $derived(athleteStore.biometrics?.series?.[athleteStore.biometrics.series.length - 1]);
  const latestLoad = $derived(
    athleteStore.metrics?.trainingLoadData?.[athleteStore.metrics.trainingLoadData.length - 1]
  );

  const firstPositiveFiniteNumber = (...candidates: unknown[]): number | null => {
    for (const v of candidates) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v;
      // Allow numeric strings, but keep the same "missing/0 => null" behavior.
      if (typeof v === 'string' && v.trim() !== '') {
        const n = Number(v);
        if (Number.isFinite(n) && n > 0) return n;
      }
    }
    return null;
  };

  const todayReadiness = $derived(firstPositiveFiniteNumber(todayBio?.readiness_score, todayBio?.recovery_score, latestBio?.readiness_score, latestBio?.recovery_score));
  const todayRecoveryScore = $derived(firstPositiveFiniteNumber(todayBio?.recovery_score, todayBio?.readiness_score));
  const todayHrv = $derived(todayBio?.hrv_rmssd ?? null);
  const todaySleepMin = $derived(todayBio?.sleep_duration_min ?? null);
  const todaySleepScore = $derived(todayBio?.sleep_score ?? null);

  const latestHrv = $derived(todayHrv ?? latestBio?.hrv_rmssd ?? null);
  const latestSleepMin = $derived(todaySleepMin ?? latestBio?.sleep_duration_min ?? null);
  const latestSleepScore = $derived(todaySleepScore ?? latestBio?.sleep_score ?? null);

  const todayHrvZ = $derived(
    typeof todayBio?.hrv_z === 'number' && Number.isFinite(todayBio.hrv_z) ? Number(todayBio.hrv_z) : null
  );
  const todayRhrZ = $derived(
    typeof todayBio?.rhr_z === 'number' && Number.isFinite(todayBio.rhr_z) ? Number(todayBio.rhr_z) : null
  );
  const latestHrvZ = $derived(
    todayHrvZ ??
      (typeof latestBio?.hrv_z === 'number' && Number.isFinite(latestBio.hrv_z) ? Number(latestBio.hrv_z) : null)
  );
  const latestRhrZ = $derived(
    todayRhrZ ??
      (typeof latestBio?.rhr_z === 'number' && Number.isFinite(latestBio.rhr_z) ? Number(latestBio.rhr_z) : null)
  );
  // The dashboard has a separate "Readiness Score" card above. This panel is explicitly "Recovery trends",
  // so prefer the raw `recovery_score` series when available.
  const latestRecovery = $derived(
    firstPositiveFiniteNumber(todayRecoveryScore, latestBio?.recovery_score, latestBio?.readiness_score)
  );

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
        return;
      }
      dashboardAiSummaryMemo.delete(endDay);
    }

    analysisText = null;

    const requestKey = `dashboard-ai-summary:${endDay}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        const res = await api.getDashboardSummary(endDay);
        const content = typeof res?.analysis?.content === 'string'
          ? _sanitizeAiSummary(res.analysis.content)
          : '';
        const next = content ? content : null;
        // Only memoize successful content so transient 401s/network hiccups don't permanently lock us into null.
        if (next) {
          dashboardAiSummaryMemo.set(endDay, next);
          _persistAiSummary(endDay, next);
        }

        if (activeAnalysisKey !== requestKey) return;
        analysisText = next;
      } catch (e) {
        console.error(e);
        if (activeAnalysisKey !== requestKey) return;
        // Keep previous text while loading/failing.
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
    <!-- Readiness Card -->
    <Card class="!bg-gradient-to-br from-blue/15 to-teal/10 border-blue/30 !p-0">
      <button 
        type="button" 
        class="w-full text-left p-4 cursor-pointer focus:outline-none"
        onclick={() => showReadinessModal = true}
        aria-label="Explain readiness score"
      >
        <div class="flex items-center gap-4">
          <RadialProgress
            value={todayReadiness ?? 0}
            max={100}
            size={64}
            color={todayReadiness === null ? 'var(--text2)' : boundedScoreCssColor(todayReadiness)}
            label={(todayReadiness ?? null) === null ? 'N/A' : String(todayReadiness)}
            sub="RDY"
          />
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-semibold text-[15px]">Readiness Score</span>
              {#if isCalibrating}
                <CalibrationBadge />
              {/if}
              {#if todayReadiness === null}
                <Tag color="var(--text2)">NO DATA</Tag>
              {:else if todayReadiness >= 67}
                <Tag color="var(--teal)">OPTIMAL</Tag>
              {:else if todayReadiness >= 34}
                <Tag color="var(--amber)">MODERATE</Tag>
              {:else}
                <Tag color="var(--red)">RECOVERY</Tag>
              {/if}
            </div>
            <p class="text-xs text-text1 leading-relaxed">
              HRV
              <span
                class={todayHrv === null ? 'text-text2' : getZScoreColor(latestHrvZ)}
                >{todayHrv === null ? 'Data not found' : `${Math.round(todayHrv)}ms`}</span>
              · Sleep
              <span
                style="color: {todaySleepMin === null || latestSleepScore === null || latestSleepScore <= 0
                  ? 'var(--text2)'
                  : boundedScoreCssColor(latestSleepScore)}"
                >{todaySleepMin === null ? 'Data not found' : sleepHM(todaySleepMin)}</span>
            </p>
            <p class="text-[11px] text-text2 mt-1">Data synced from your connected services.</p>
          </div>
        </div>
      </button>
    </Card>

    <!-- Metric Row: CTL/ATL use chart identity colors; TSB uses form/status bands -->
    <div class="grid grid-cols-3 gap-2.5">
      <Card style="padding: 12px 14px;">
        <div class="flex justify-between items-start">
          <MetricBadge label="CTL" value={todayCtl === null ? 'Data not found' : Math.round(todayCtl)} unit="" color={CTL_IDENTITY_HEX} sub="Fitness" />
          {#if isCalibrating}
            <CalibrationBadge />
          {/if}
        </div>
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="ATL" value={todayAtl === null ? 'Data not found' : Math.round(todayAtl)} unit="" color={ATL_IDENTITY_HEX} sub="Fatigue" />
      </Card>
      <Card style="padding: 12px 14px;">
        <div class="flex justify-between items-start">
          <MetricBadge
            label="TSB"
            value={todayTsb === null ? 'Data not found' : (todayTsb > 0 ? `+${Math.round(todayTsb)}` : Math.round(todayTsb))}
            unit=""
            color={todayTsb === null ? 'var(--text2)' : formCssColor(todayTsb)}
            sub="Form"
          />
          {#if isCalibrating}
            <CalibrationBadge />
          {/if}
        </div>
      </Card>
    </div>

    <!-- AI Summary -->
    <Card class="!bg-gradient-to-br from-blue/10 via-transparent to-transparent">
      <div class="flex justify-between items-center mb-2">
        <span class="text-[13px] font-semibold">AI Summary</span>
        <Tag color="var(--blue)">BETA</Tag>
      </div>
      <p class="text-xs text-text1 leading-relaxed">
        {analysisText ?? fallbackSummary}
      </p>
    </Card>

    {#if athleteStore.metrics?.trainingLoadData?.length > 0}
      <Card>
        <div class="flex justify-between items-center mb-3">
          <span class="text-[13px] font-semibold">Training Load</span>
          <div class="flex gap-3">
            <span class="text-[10px] font-mono flex items-center gap-1 text-chartCtl">
              <span class="w-4 h-0.5 bg-chartCtl inline-block rounded-[1px]"></span> CTL
            </span>
            <span class="text-[10px] font-mono flex items-center gap-1 text-text2">
              <span class="w-2.5 h-2.5 bg-chartAtl/80 inline-block rounded-sm"></span> ATL
            </span>
          </div>
        </div>
        <MultiLineChart data={athleteStore.metrics.trainingLoadData} height={110} />
      </Card>
    {/if}

    <!-- Recovery trends + Sleep -->
    <div class="grid grid-cols-2 gap-2.5">
      <Card>
        <div class="flex justify-between items-start mb-2">
          <span class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em]">Recovery trends</span>
          {#if todayReadiness === null && latestRecovery !== null}
            <span class="text-[8px] bg-glass px-1 rounded text-text2 border border-border uppercase">Latest</span>
          {/if}
        </div>
        <div class="flex items-baseline gap-1.5">
          <span class="text-[20px] font-bold" style="color: {latestRecovery === null ? 'var(--text2)' : recoveryColor(Number(latestRecovery))}">
            {latestRecovery === null ? 'Data not found' : Math.round(Number(latestRecovery))}
            <span class="text-[11px] text-text2 font-normal">/100</span>
          </span>
        </div>
        <p class="text-[10px] text-text2 mt-1">
          7d avg <span class="text-text1 font-medium">{avgRecovery7d === null ? '--' : `${avgRecovery7d}/100`}</span>
        </p>
        {#if recoveryTrendData.length > 1}
          <div class="mt-2">
            <TrendBars
              data={recoveryTrendData}
              labels={recoveryTrendLabels}
              keys={recoveryTrendKeys}
              height={48}
              min={0}
              max={100}
              getValueColor={(v) => recoveryColor(v)}
              formatValue={(v) => `${Math.round(Number(v))}`}
              unit="/100"
              showBottomLabels={true}
              onSelect={({ key }) => {
                if (!key) return;
                goto(resolve(`/recovery?day=${encodeURIComponent(String(key))}`));
              }}
            />
          </div>
        {:else}
          <div class="h-[48px] flex items-center justify-center text-[10px] text-text2 italic">Pending data...</div>
        {/if}
      </Card>
      
      <Card>
        <div class="flex justify-between items-start mb-2">
          <span class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em]">Sleep</span>
          {#if todaySleepMin === null && latestSleepMin !== null}
            <span class="text-[8px] bg-glass px-1 rounded text-text2 border border-border uppercase">Latest</span>
          {/if}
        </div>
        <div class="flex items-baseline gap-1.5">
          <span
            class="text-[20px] font-bold"
            style="color: {latestSleepMin === null || latestSleepScore === null || latestSleepScore <= 0
              ? 'var(--text2)'
              : boundedScoreCssColor(latestSleepScore)}"
          >
            {latestSleepMin === null ? 'Data not found' : sleepHM(latestSleepMin)}
          </span>
        </div>
        <p class="text-[10px] text-text2 mt-1">
          7d avg
          <span
            class="font-medium"
            style="color: {avgSleep7dMin === null || avgSleepScore7d === null || avgSleepScore7d <= 0
              ? 'var(--text2)'
              : boundedScoreCssColor(avgSleepScore7d)}"
            >{avgSleep7dMin === null ? '--' : sleepHM(avgSleep7dMin)}</span>
          <span class="text-text2"> · </span>
          <span
            class="font-medium"
            style="color: {avgSleepScore7d === null || avgSleepScore7d <= 0
              ? 'var(--text2)'
              : boundedScoreCssColor(avgSleepScore7d)}"
          >
            {avgSleepScore7d === null ? '--' : `${avgSleepScore7d}%`}
          </span>
        </p>
        {#if sleepTrendData.length > 1}
          <div class="mt-2">
            <TrendBars
              data={sleepTrendData}
              labels={sleepTrendLabels}
              keys={sleepTrendKeys}
              height={48}
              min={0}
              max={100}
              getValueColor={(v) => sleepColor(v)}
              formatValue={(v) => `${Math.round(Number(v))}`}
              unit="%"
              showBottomLabels={true}
              onSelect={({ key }) => {
                if (!key) return;
                goto(resolve(`/sleep?day=${encodeURIComponent(String(key))}`));
              }}
            />
          </div>
        {:else}
          <div class="h-[48px] flex items-center justify-center text-[10px] text-text2 italic">Pending data...</div>
        {/if}
      </Card>
    </div>

    <!-- Recent Activity -->
    {#if athleteStore.workouts?.length > 0}
      <Card>
        <div class="flex justify-between items-center mb-3">
          <span class="text-[13px] font-semibold">Recent Activity</span>
          <Tag color="var(--blue)">SYNCED</Tag>
        </div>
        <div class="flex flex-col gap-2.5">
          {#each athleteStore.workouts.slice(0, 3) as w, i (w.id)}
            {@const type = w.sport?.toLowerCase()}
            {@const strainVal = Number.isFinite(Number(w?.strain_score)) ? Math.round(Number(w.strain_score)) : null}
            {@const tssVal = Number.isFinite(Number(w?.tss)) ? Math.round(Number(w.tss)) : null}
            <button
              type="button"
              class="text-left bg-transparent border-none p-0 cursor-pointer w-full"
              onclick={() => goto(resolve(`/training?workout_id=${encodeURIComponent(String(w.id))}`))}
              aria-label="View workout details"
            >
              <div class="flex items-center gap-3 py-2.5 {i < 2 ? 'border-b border-border' : ''}">
                <div class="w-9 h-9 rounded-xl shrink-0 flex items-center justify-center text-[15px]
                  {type === 'run' || type === 'running' ? 'bg-blue-dim border border-blue/30' :
                   type === 'bike' || type === 'cycling' ? 'bg-teal-dim border border-teal/30' :
                   type === 'row' || type === 'rowing' ? 'bg-amber-dim border border-amber/30' :
                   type === 'swim' || type === 'swimming' ? 'bg-glass border border-border' :
                   type === 'mobility' ? 'bg-glass border border-[rgba(168,85,247,0.35)]' :
                   type === 'other' ? 'bg-glass border border-[rgba(234,179,8,0.35)]' :
                   'bg-glass border border-border'}">
                  {type === 'run' || type === 'running' ? '🏃' : (type === 'bike' || type === 'cycling') ? '🚴' : type === 'row' || type === 'rowing' ? '🚣' : type === 'swim' || type === 'swimming' ? '🏊' : type === 'mobility' ? '🧘' : '⭐'}
                </div>
                <div class="flex-1">
                  <p class="text-[13px] font-medium text-text0">{w.title || (w.sport?.toUpperCase() + ' Session')}</p>
                  <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(w.duration_secs / 60)} min</p>
                </div>
                <div class="text-right flex flex-col gap-1">
                  <div>
                    <p class="text-[13px] font-semibold tabular-nums" style:color={boundedScoreCssColor(strainVal, true)}>
                      {strainVal === null ? '--' : strainVal}
                    </p>
                    <p class="text-[9px] text-text2 font-mono">STRAIN</p>
                  </div>
                  <div>
                    <p
                      class="text-[13px] font-semibold tabular-nums"
                      style:color={boundedScoreCssColor(tssVal === null ? null : strainVal, true)}
                    >
                      {tssVal === null ? '--' : tssVal}
                    </p>
                    <p class="text-[9px] text-text2 font-mono">TSS</p>
                  </div>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </Card>
    {/if}
  {/if}
</div>

<Modal 
  show={showReadinessModal} 
  title="Readiness vs. Recovery" 
  onClose={() => showReadinessModal = false}
>
  <div class="space-y-4">
    <p class="text-[14px] leading-relaxed text-text1">
      While often used interchangeably, <span class="font-bold text-text0">Readiness</span> and <span class="font-bold text-text0">Recovery</span> measure two different aspects of your training capacity in Astraphe.
    </p>

    <div class="space-y-3">
      <div class="p-4 rounded-2xl bg-glass border border-border">
        <h3 class="text-[13px] font-bold text-text0 mb-1">Recovery (Physiological)</h3>
        <p class="text-[12px] text-text1 leading-relaxed">
          Driven by your Autonomic Nervous System. We combine your <strong>Heart Rate Variability (HRV)</strong>, <strong>Resting Heart Rate</strong>, and <strong>Sleep Quality</strong> against your 30-day baselines to determine how your body bounced back from yesterday's strain.
        </p>
      </div>

      <div class="p-4 rounded-2xl bg-glass border border-border">
        <h3 class="text-[13px] font-bold text-text0 mb-1">Readiness (Training Load)</h3>
        <p class="text-[12px] text-text1 leading-relaxed">
          Also known as "Form," this is driven by your Training Stress Balance (TSB). It compares your long-term <strong>Fitness</strong> against your short-term <strong>Fatigue</strong>. You can be fully <em>recovered</em> (slept well) but have low <em>readiness</em> if you are deep in a heavy training block.
        </p>
      </div>
    </div>

    <p class="text-[12px] text-text2 italic border-t border-border pt-4">
      Your dashboard highlights whichever score provides the clearest signal for your daily training capacity. Scores above 67 indicate an optimal state for hard training, while scores below 34 suggest focusing on active recovery.
    </p>
  </div>
</Modal>
