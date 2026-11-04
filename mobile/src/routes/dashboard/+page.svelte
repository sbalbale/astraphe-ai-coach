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
  import Tag from '$lib/components/Tag.svelte';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import DashedNote from '$lib/components/ui/DashedNote.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';
  import GetSetUpCard, { type SetupStep } from '$lib/components/dashboard/GetSetUpCard.svelte';
  import { pageHeader } from '$lib/stores/pageHeader.svelte';
  import { viewport } from '$lib/stores/viewport.svelte';
  import WideToday from '$lib/components/wide/today/WideToday.svelte';
  import { daySessions } from '$lib/components/wide/today/todayWide';
  import PhoneSessionCard from '$lib/components/dashboard/PhoneSessionCard.svelte';
  import { firstName, isProfileComplete } from '$lib/utils/profile';
  import { addDays } from 'date-fns';
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
  const currentGreeting = $derived(getTimeOfDayGreeting(greetingNow));

  onMount(() => {
    athleteStore.fetchAll();
    // Keep "today" current: the app can sit open (or backgrounded) across
    // midnight, and the summary, key session and load all key off today's date.
    const refreshClock = () => {
      const now = new Date();
      const dayChanged = format(now, 'yyyy-MM-dd') !== format(greetingNow, 'yyyy-MM-dd');
      greetingNow = now;
      if (dayChanged) athleteStore.fetchAll(true);
    };
    refreshClock();
    const greetingTimer = window.setInterval(refreshClock, 60_000);
    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshClock();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      window.clearInterval(greetingTimer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });

  const isCalibrating = $derived(
    athleteStore.initialLoadDone &&
    athleteStore.days_on_platform > 0 &&
    athleteStore.days_on_platform < 42
  );
  // --- Today's planned sessions (hardest first: the first is the key session) ---
  let plannedWorkouts = $state<Workout[]>([]);
  const todayIso = $derived(format(greetingNow, 'yyyy-MM-dd'));
  /** Bumped when the wide layout moves a session, so today's plan reloads. */
  let planReload = $state(0);

  $effect(() => {
    const iso = todayIso; // re-fetch when the day rolls over
    void planReload;
    let cancelled = false;
    api.getWorkouts(iso, iso).then(
      (rows) => {
        if (!cancelled) plannedWorkouts = rows;
      },
      (e) => console.warn('[Dashboard] planned workouts failed:', e)
    );
    return () => {
      cancelled = true;
    };
  });

  const todaySessions = $derived(daySessions(plannedWorkouts, todayIso));
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);

  const hasData = $derived(athleteStore.workouts?.length > 0 || athleteStore.readiness > 0);
  const isConnected = $derived(Object.values(athleteStore.syncStatus?.integrations || {}).some((i: any) => i.connected));
  // "Connect an app" only when we *know* nothing is connected and there's no data:
  // manual-only athletes (logged sleep/workouts) see their data, and connected users
  // don't flash this while the sync status is still loading.
  const showConnectPrompt = $derived(athleteStore.syncStatus != null && !isConnected && !hasData);

  // --- New account: "Get set up" checklist (design: empty states, page 1) ---
  const greetingName = $derived(
    firstName(athleteStore.profile?.display_name, authStore.user?.user_metadata?.full_name)
  );
  $effect(() => {
    pageHeader.title = showConnectPrompt ? (greetingName ? `Welcome, ${greetingName}` : 'Welcome') : '';
    // Wide header (design: "Good morning, Sean" over "MONDAY 2 NOVEMBER"); the welcome title wins.
    pageHeader.wideTitle = showConnectPrompt ? '' : greetingName ? `${currentGreeting}, ${greetingName}` : currentGreeting;
    pageHeader.wideEyebrow = format(greetingNow, 'EEEE d MMMM');
    return () => {
      pageHeader.title = '';
      pageHeader.wideTitle = '';
      pageHeader.wideEyebrow = '';
    };
  });

  /** Any planned session in the next four weeks counts as "has a plan". */
  let hasUpcomingPlan = $state(false);
  $effect(() => {
    if (!showConnectPrompt) return;
    const from = todayIso;
    let cancelled = false;
    api.getWorkouts(from, format(addDays(new Date(from + 'T12:00:00'), 28), 'yyyy-MM-dd')).then(
      (rows) => {
        if (!cancelled) hasUpcomingPlan = rows.length > 0;
      },
      () => {}
    );
    return () => {
      cancelled = true;
    };
  });

  const setupSteps = $derived<SetupStep[]>([
    {
      title: 'Create your profile',
      detail: 'Sport, units and the basics your zones are built from',
      done: isProfileComplete(athleteStore.profile),
      actionLabel: 'Finish',
      onAction: () => goto('/onboarding'),
    },
    {
      title: 'Connect a wearable',
      detail: 'Garmin or WHOOP · imports the last 90 days',
      done: isConnected,
      actionLabel: 'Connect',
      onAction: () => goto('/profile/connections'),
    },
    {
      title: 'Get your first plan',
      detail: 'Tell your coach your goal — it builds week 1',
      done: hasUpcomingPlan,
      actionLabel: 'Start',
      onAction: () => goto(`/chat?prompt=${encodeURIComponent('Build me a plan for my goal.')}`),
    },
  ]);


  const todayStr = $derived(todayIso);
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

  // --- Waiting for last night's sleep (design: empty states, page 2) ---
  /** Connected and has history, but today's row hasn't synced: readiness can't be computed yet. */
  const waitingForSleep = $derived(isConnected && !!current.row && !current.hasTodayRow);
  const sleepProvider = $derived.by(() => {
    const i = athleteStore.syncStatus?.integrations ?? {};
    if (i.whoop?.connected) return 'WHOOP';
    if (i.garmin?.connected) return 'Garmin';
    return 'your device';
  });
  /** The last readiness we do have, and how to name its day. */
  const previousReadiness = $derived(waitingForSleep ? readinessScoreFromRow(current.row) : null);
  const previousReadinessDay = $derived.by(() => {
    if (!current.date) return 'Yesterday';
    const yesterday = format(addDays(new Date(todayIso + 'T12:00:00'), -1), 'yyyy-MM-dd');
    return current.date === yesterday ? 'Yesterday' : format(new Date(current.date + 'T12:00:00'), 'EEE d MMM');
  });
  let checking = $state(false);
  async function checkAgain() {
    checking = true;
    try {
      await athleteStore.fetchAll(true);
    } finally {
      checking = false;
    }
  }

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

  /** Readiness card data for the wide layout (same values as the phone card). */
  const wideReadiness = $derived({
    score: todayReadiness,
    recovery: todayRecoveryScore === null ? null : Number(todayRecoveryScore),
    hrv: latestHrv,
    sleepLabel: latestSleepMin === null ? null : sleepHM(latestSleepMin),
    form: isFiniteNumber(todayTsb) ? todayTsb : null,
    stale: current.isStale,
    notes: [
      ...(isCalibrating ? ['Calibrating · fitness and form firm up after 42 days'] : []),
      ...(carryOverLabel ? [carryOverLabel] : []),
      ...(current.isStale
        ? [`Last synced ${current.ageHours != null ? Math.round(current.ageHours) : '—'}h ago — sync your device`]
        : [])
    ]
  });

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
  {#if showConnectPrompt}
    <GetSetUpCard steps={setupSteps} />

    <p class="font-mono text-[12px] tracking-[0.2em] text-text2 uppercase mt-4 mb-1 px-1">Once you're connected</p>
    <DashedNote>
      <div class="flex items-center gap-5">
        <div class="w-[72px] h-[72px] shrink-0 rounded-[22px] border-[6px] border-bg3" aria-hidden="true"></div>
        <div>
          <p class="m-0 text-[17px] font-medium text-text0">Daily readiness</p>
          <p class="m-0 text-[15px] text-text1 leading-snug mt-1">Appears after your first night of sleep is synced.</p>
        </div>
      </div>
    </DashedNote>
    <DashedNote>
      <div class="flex items-center gap-5">
        <div class="w-[72px] h-[48px] shrink-0 flex items-end gap-1.5" aria-hidden="true">
          {#each [10, 34, 10, 34, 6] as h, i (i)}
            <div class="flex-1 rounded-[3px] bg-bg3" style="height: {h}px"></div>
          {/each}
        </div>
        <div>
          <p class="m-0 text-[17px] font-medium text-text0">Today's session</p>
          <p class="m-0 text-[15px] text-text1 leading-snug mt-1">Your coach picks it from your plan and how recovered you are.</p>
        </div>
      </div>
    </DashedNote>
  {:else if !hasData}
    <EmptyStateCard
      icon="refresh"
      tone="amber"
      eyebrow="Waiting for sync"
      title="Your first sync is on its way"
      message="Your apps are connected. Workouts and sleep appear here after the first sync, usually within a few minutes."
      actionLabel={checking ? 'Checking…' : 'Check again'}
      onAction={checkAgain}
      secondaryLabel="Connected apps"
      onSecondary={() => goto('/profile/connections')}
    />
  {:else}

    {#if waitingForSleep}
      <!-- Readiness can't be scored until last night's sleep syncs -->
      <section aria-label="Readiness" class="bg-bg2 border border-amber/25 rounded-card px-6 py-6">
        <div class="flex gap-6">
          <div class="flex flex-col min-w-[92px]">
            <span class="font-mono text-[11px] tracking-[0.18em] text-text2">READINESS</span>
            <span class="block w-8 h-[3px] rounded-full bg-text2/60 mt-8 mb-6" aria-label="No score yet"></span>
            <span class="text-[15px] text-amber">Waiting for sleep</span>
          </div>
          <dl class="m-0 flex-1 grid grid-cols-2 gap-x-3 gap-y-4">
            {#each [['Recovery', null], ['HRV', null], ['Sleep', null]] as [label] (label)}
              <div>
                <dt class="text-[14px] text-text2">{label}</dt>
                <dd class="m-0 mt-2"><span class="block w-5 h-[2px] bg-text2/60" aria-label="Not yet"></span></dd>
              </div>
            {/each}
            <div>
              <dt class="text-[14px] text-text2">Form</dt>
              <dd class="m-0 text-[20px] font-medium text-text0">{todayTsb === null ? '--' : (todayTsb > 0 ? `+${todayTsb.toFixed(1)}` : todayTsb.toFixed(1))}</dd>
            </div>
          </dl>
        </div>
        <p class="text-[16px] leading-relaxed text-text1 mt-5 mb-5">
          Last night's sleep hasn't arrived from {sleepProvider} yet — it usually syncs within 30 minutes of waking.
          {#if previousReadiness !== null}
            {previousReadinessDay}'s readiness was <span class="text-text0">{previousReadiness}</span>.
          {/if}
        </p>
        <div class="flex items-center gap-4">
          <Button variant="secondary" full={false} size="sm" class="!h-12 !px-5" onclick={checkAgain} disabled={checking}>
            <UiIcon name="refresh" size={16} />
            {checking ? 'Checking…' : 'Check again'}
          </Button>
          <Button variant="ghost" full={false} size="sm" class="!h-12" onclick={() => goto('/sleep?log=1')}>Log sleep myself</Button>
        </div>
      </section>
    {/if}

    {#if viewport.wide}
      <WideToday
        {todayIso}
        landscape={viewport.landscape}
        {ftp}
        provisional={waitingForSleep}
        readiness={waitingForSleep ? null : wideReadiness}
        coachNote={analysisText ?? fallbackSummary}
        onPlanChanged={() => planReload++}
      />
    {:else}
    <!-- Today's sessions: every one planned, the hardest first -->
    {#if todaySessions.length > 0}
      {#each todaySessions as w, i (w.id)}
        <PhoneSessionCard workout={w} {ftp} label={i === 0 ? 'Key session' : 'Also today'} provisional={waitingForSleep} />
      {/each}
    {:else}
      <section aria-label="Key session" class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-3.5">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">NO SESSION PLANNED</span>
        <h2 class="m-0 font-display font-normal text-[34px] leading-[1.05]">Rest day</h2>
        <p class="m-0 text-sm leading-[1.45] text-text1">Nothing on the plan. Ask your coach if you want to add something.</p>
      </section>
    {/if}

    <!-- Readiness Card -->
    {#if !waitingForSleep}
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
    {/if}

    <!-- AI Summary -->
    <a href={resolve('/chat')} class="flex items-start gap-3 px-[18px] py-4 rounded-[20px] bg-bg1 border border-dashed border-border">
      <span aria-hidden="true" class="shrink-0 w-7 h-7 rounded-full bg-blue-dim text-blue flex items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 18c3-8 13-8 16 0"></path><path d="M8 18c1.5-4 6.5-4 8 0"></path></svg>
      </span>
      <span class="text-[13px] leading-[1.45] text-text1">{analysisText ?? fallbackSummary}</span>
    </a>
    {/if}
  {/if}
</div>


