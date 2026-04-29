<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import MetricBadge from '$lib/components/MetricBadge.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import RadialProgress from '$lib/components/RadialProgress.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import LineChart from '$lib/components/charts/LineChart.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import CalibrationBadge from '$lib/components/CalibrationBadge.svelte';
  import { onMount } from 'svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';
  import { format } from 'date-fns';

  const props = $props();

  onMount(() => {
    athleteStore.fetchAll(true);
  });

  const isCalibrating = $derived(athleteStore.days_on_platform < 42);
  const hasData = $derived(athleteStore.workouts?.length > 0 || athleteStore.readiness > 0);
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));

  const todayStr = $derived(format(new Date(), 'yyyy-MM-dd'));
  const isoDate = (v: unknown) => (typeof v === 'string' ? v.slice(0, 10) : '');

  const todayBio = $derived(athleteStore.biometrics?.series?.find((s: any) => s.date === todayStr));
  const todayLoad = $derived(athleteStore.metrics?.trainingLoadData?.find((m: any) => isoDate(m?.date) === todayStr));

  const todayReadiness = $derived(todayBio?.astrape_recovery_score ?? todayBio?.recovery_score ?? null);
  const todayHrv = $derived(todayBio?.hrv_rmssd ?? null);
  const todaySleepMin = $derived(todayBio?.sleep_duration_min ?? null);
  const todaySleepScore = $derived(todayBio?.astrape_sleep_score ?? todayBio?.sleep_score ?? null);

  const latestBio = $derived(athleteStore.biometrics?.series?.[athleteStore.biometrics.series.length - 1]);
  const latestHrv = $derived(todayHrv ?? latestBio?.hrv_rmssd ?? null);
  const latestSleepMin = $derived(todaySleepMin ?? latestBio?.sleep_duration_min ?? null);
  const latestSleepScore = $derived(todaySleepScore ?? latestBio?.astrape_sleep_score ?? latestBio?.sleep_score ?? null);

  const todayCtl = $derived(todayLoad?.ctl ?? null);
  const todayAtl = $derived(todayLoad?.atl ?? null);
  const todayTsb = $derived(todayLoad?.tsb ?? null);

  const sleepHM = (mins: number | null) => {
    if (mins === null || mins === undefined) return 'Data not found';
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    const r = m % 60;
    return `${h}h ${r}m`;
  };

  const hrvColor = (val: number) => {
    const base = Number(athleteStore.profile?.hrv_baseline) || 0;
    if (!base) return '#00C8A8';
    if (val >= base * 1.05) return '#00C8A8';
    if (val >= base * 0.95) return '#FFCB88';
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

  const avgSleep7dMin = $derived.by(() => {
    const src = (athleteStore.biometrics?.sleepData || []).slice(-7); // hours (float)
    const a = avg(src.map((v: unknown) => Number(v)).filter((v: number) => v > 0));
    return a === null ? null : Math.round(a * 60);
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

    <!-- HRV + Sleep -->
    <div class="grid grid-cols-2 gap-2.5">
      <Card>
        <div class="flex justify-between items-start mb-2">
          <span class="text-[9px] text-text2 font-mono uppercase tracking-[0.08em]">HRV Trend</span>
          {#if todayHrv === null && latestHrv !== null}
            <span class="text-[8px] bg-white/5 px-1 rounded text-text2 border border-white/5 uppercase">Latest</span>
          {/if}
        </div>
        <div class="flex items-baseline gap-1.5">
          <span class="text-[20px] font-bold" style="color: {latestHrv === null ? 'var(--text2)' : hrvColor(Number(latestHrv))}">
            {latestHrv === null ? 'Data not found' : Math.round(latestHrv)}
            <span class="text-[11px] text-text2 font-normal">ms</span>
          </span>
        </div>
        <p class="text-[10px] text-text2 mt-1">
          7d avg <span class="text-text1 font-medium">{avgHrv7d === null ? '--' : `${avgHrv7d}ms`}</span>
        </p>
        {#if athleteStore.biometrics?.hrvData?.length > 1}
          <div class="mt-2">
            <LineChart
              data={athleteStore.biometrics.hrvData}
              color={latestHrv === null ? '#00C8A8' : hrvColor(Number(latestHrv))}
              height={48}
              formatValue={(v) => `${Math.round(Number(v))}`}
              getValueColor={(v) => hrvColor(v)}
              unit="ms"
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
        </p>
        {#if (athleteStore.biometrics?.sleepScores?.length || 0) > 1}
          <div class="mt-2">
            <LineChart
              data={athleteStore.biometrics.sleepScores}
              color={sleepColor(latestSleepScore)}
              height={48}
              formatValue={(v) => `${v}%`}
              getValueColor={(v) => sleepColor(v)}
            />
          </div>
        {:else if (athleteStore.biometrics?.sleepData?.length || 0) > 1}
          <div class="mt-2">
            <LineChart
              data={athleteStore.biometrics.sleepData}
              color={latestSleepMin === null ? '#FFCB88' : sleepColor(latestSleepScore)}
              height={48}
              formatValue={formatSleepHours}
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
          {#each athleteStore.workouts.slice(0, 3) as w, i}
            {@const type = w.sport?.toLowerCase()}
            <button
              type="button"
              class="text-left bg-transparent border-none p-0 cursor-pointer w-full"
              onclick={() => goto(`/training?workout_id=${encodeURIComponent(String(w.id))}`)}
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
                <div class="text-right">
                  <p class="text-[13px] font-semibold {w.tss > 75 ? 'text-red' : w.tss > 55 ? 'text-amber' : 'text-teal'}">{Math.round(w.tss || 0)}</p>
                  <p class="text-[9px] text-text2 font-mono">TSS</p>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </Card>
    {/if}
  {/if}
</div>
