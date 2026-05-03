<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const dashboardAiSummaryMemo = new SvelteMap<string, string | null>();
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
  import { onMount } from 'svelte';
  import { analysisNavEpoch } from '$lib/analysisNavEpoch.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { api } from '$lib/api';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { format } from 'date-fns';
  import { strainTextClass, tssTextClass } from '$lib/scoreColors';

  const props = $props();

  onMount(() => {
    athleteStore.fetchAll(true);
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

  const todayReadiness = $derived(firstPositiveFiniteNumber(todayBio?.readiness_score, todayBio?.recovery_score));
  const todayRecoveryScore = $derived(firstPositiveFiniteNumber(todayBio?.recovery_score, todayBio?.readiness_score));
  const todayHrv = $derived(todayBio?.hrv_rmssd ?? null);
  const todaySleepMin = $derived(todayBio?.sleep_duration_min ?? null);
  const todaySleepScore = $derived(todayBio?.sleep_score ?? null);

  const latestBio = $derived(athleteStore.biometrics?.series?.[athleteStore.biometrics.series.length - 1]);
  const latestHrv = $derived(todayHrv ?? latestBio?.hrv_rmssd ?? null);
  const latestSleepMin = $derived(todaySleepMin ?? latestBio?.sleep_duration_min ?? null);
  const latestSleepScore = $derived(todaySleepScore ?? latestBio?.sleep_score ?? null);
  // The dashboard has a separate "Readiness Score" card above. This panel is explicitly "Recovery trends",
  // so prefer the raw `recovery_score` series when available.
  const latestRecovery = $derived(
    firstPositiveFiniteNumber(todayRecoveryScore, latestBio?.recovery_score, latestBio?.readiness_score)
  );

  const todayCtl = $derived(todayLoad?.ctl ?? null);
  const todayAtl = $derived(todayLoad?.atl ?? null);
  const todayTsb = $derived(todayLoad?.tsb ?? null);

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
      analysisText = cached;
      return;
    }

    analysisText = null;

    const requestKey = `dashboard-ai-summary:${endDay}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        const res = await api.getDashboardSummary(endDay);
        const content = typeof res?.analysis?.content === 'string' ? res.analysis.content.trim() : '';
        const next = content ? content : null;
        // Only memoize successful content so transient 401s/network hiccups don't permanently lock us into null.
        if (next) dashboardAiSummaryMemo.set(endDay, next);

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

  const recoveryColor = (score: number) => {
    if (score >= 67) return '#00C8A8';
    if (score >= 34) return '#FFCB88';
    return '#F07178';
  };

  const sleepColor = (score: number | null) => {
    if (score === null || score === undefined) return 'var(--text2)';
    if (score >= 67) return '#00C8A8'; // Green
    if (score >= 34) return '#FFCB88'; // Yellow/Amber
    return '#F07178'; // Red
  };
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
      <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">{format(new Date(), 'EEEE, MMM d')}</p>
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Good morning, {authStore.user?.user_metadata?.full_name || 'Athlete'}</h1>
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
    <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.18) 0%, rgba(0,200,168,0.10) 100%); border-color: rgba(70,33,255,0.3);">
      <div class="flex items-center gap-4">
        <RadialProgress
          value={todayReadiness ?? 0}
          max={100}
          size={64}
          color="#4621FF"
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
            {:else if todayReadiness > 70}
              <Tag color="var(--teal)">OPTIMAL</Tag>
            {:else if todayReadiness > 40}
              <Tag color="var(--amber)">MODERATE</Tag>
            {:else}
              <Tag color="var(--red)">RECOVERY</Tag>
            {/if}
          </div>
          <p class="text-xs text-text1 leading-relaxed">
            HRV {todayHrv === null ? 'Data not found' : `${Math.round(todayHrv)}ms`} · Sleep {todaySleepMin === null ? 'Data not found' : sleepHM(todaySleepMin)}
          </p>
          <p class="text-[11px] text-text2 mt-1">Data synced from your connected services.</p>
        </div>
      </div>
    </Card>

    <!-- Metric Row -->
    <div class="grid grid-cols-3 gap-2.5">
      <Card style="padding: 12px 14px;">
        <div class="flex justify-between items-start">
          <MetricBadge label="CTL" value={todayCtl === null ? 'Data not found' : Math.round(todayCtl)} unit="" color="var(--teal)" sub="Fitness" />
          {#if isCalibrating}
            <CalibrationBadge />
          {/if}
        </div>
      </Card>
      <Card style="padding: 12px 14px;">
        <MetricBadge label="ATL" value={todayAtl === null ? 'Data not found' : Math.round(todayAtl)} unit="" color="var(--amber)" sub="Fatigue" />
      </Card>
      <Card style="padding: 12px 14px;">
        <div class="flex justify-between items-start">
          <MetricBadge
            label="TSB"
            value={todayTsb === null ? 'Data not found' : (todayTsb > 0 ? `+${Math.round(todayTsb)}` : Math.round(todayTsb))}
            unit=""
            color="#4621FF"
            sub="Form"
          />
          {#if isCalibrating}
            <CalibrationBadge />
          {/if}
        </div>
      </Card>
    </div>

    <!-- AI Summary -->
    <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);">
      <div class="flex justify-between items-center mb-2">
        <span class="text-[13px] font-semibold">AI Summary</span>
        <Tag color="var(--blue)">BETA</Tag>
      </div>
      <p class="text-xs text-text1 leading-relaxed">
        {analysisText ?? fallbackSummary}
      </p>
    </Card>

    <!-- Training Load Chart -->
    {#if athleteStore.metrics?.trainingLoadData?.length > 0}
      <Card>
        <div class="flex justify-between items-center mb-3">
          <span class="text-[13px] font-semibold">Training Load</span>
          <div class="flex gap-3">
            <span class="text-[10px] text-teal font-mono flex items-center gap-1">
              <span class="w-4 h-0.5 bg-teal inline-block rounded-[1px]"></span> CTL
            </span>
            <span class="text-[10px] text-blue font-mono flex items-center gap-1">
              <span class="w-2.5 h-2.5 bg-blue/40 inline-block rounded-sm"></span> ATL
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
            <span class="text-[8px] bg-white/5 px-1 rounded text-text2 border border-white/5 uppercase">Latest</span>
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
            <span class="text-[8px] bg-white/5 px-1 rounded text-text2 border border-white/5 uppercase">Latest</span>
          {/if}
        </div>
        <div class="flex items-baseline gap-1.5">
          <span class="text-[20px] font-bold" style="color: {sleepColor(latestSleepScore)}">
            {latestSleepMin === null ? 'Data not found' : sleepHM(latestSleepMin)}
          </span>
        </div>
        <p class="text-[10px] text-text2 mt-1">
          7d avg <span class="text-text1 font-medium">{avgSleep7dMin === null ? '--' : sleepHM(avgSleep7dMin)}</span>
          <span class="text-text2"> · </span>
          <span class="text-text1 font-medium">{avgSleepScore7d === null ? '--' : `${avgSleepScore7d}%`}</span>
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
                  {type === 'run' ? 'bg-blue-dim border border-[rgba(70,33,255,0.3)]' : 
                   type === 'bike' || type === 'cycling' ? 'bg-teal-dim border border-[rgba(0,200,168,0.3)]' : 
                   type === 'rowing' ? 'bg-amber-dim border border-[rgba(255,203,136,0.3)]' :
                   'bg-glass border border-border'}">
                  {type === 'run' ? '🏃' : (type === 'bike' || type === 'cycling') ? '🚴' : type === 'rowing' ? '🚣' : '💪'}
                </div>
                <div class="flex-1">
                  <p class="text-[13px] font-medium">{w.title || (w.sport?.toUpperCase() + ' Session')}</p>
                  <p class="text-[11px] text-text2">{format(new Date(w.started_at), 'MMM d')} · {Math.floor(w.duration_secs / 60)} min</p>
                </div>
                <div class="text-right flex flex-col gap-1">
                  <div>
                    <p class="text-[13px] font-semibold {strainVal === null ? 'text-text2' : strainTextClass(strainVal)}">
                      {strainVal === null ? '--' : strainVal}
                    </p>
                    <p class="text-[9px] text-text2 font-mono">STRAIN</p>
                  </div>
                  <div>
                    <p class="text-[13px] font-semibold {tssVal === null ? 'text-text2' : tssTextClass(tssVal)}">
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
