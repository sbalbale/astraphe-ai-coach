<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const sleepAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from "$lib/components/Card.svelte";
  import Tag from "$lib/components/Tag.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import RadialProgress from "$lib/components/RadialProgress.svelte";
  import {
    boundedScoreCssColor,
    sleepDebtCssColor,
    getBoundedScoreColor,
    zScoreCssColor
  } from "$lib/scoreColors";
  import { analysisNavEpoch } from "$lib/analysisNavEpoch.svelte";
  import { athleteStore } from "$lib/stores/athleteStore.svelte";
  import { api } from "$lib/api";
  import { addDays, format, parseISO, subDays } from "date-fns";
  import { calculateSleepScore, currentRecoveryState } from "$lib/utils/biometrics";
  import { onMount } from "svelte";
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { page } from "$app/stores";
  import AddSleepModal from "$lib/components/AddSleepModal.svelte";

  const isConnected = $derived(
    Object.values(athleteStore.syncStatus?.integrations || {}).some(
      (i: any) => i.connected,
    ),
  );
  const hasData = $derived(athleteStore.biometrics?.series?.length > 0);

  function formatHoursMinutesFromMinutes(mins: number | null | undefined): string {
    const n = typeof mins === "number" ? mins : Number(mins);
    if (!Number.isFinite(n)) return "--";
    const m = Math.max(0, Math.round(n));
    const h = Math.floor(m / 60);
    const r = m % 60;
    return `${h}h ${r}m`;
  }

  function metricPresent(value: unknown): boolean {
    return typeof value === "number" && Number.isFinite(value);
  }


  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state("");
  let nightIndex = $state(6); // most recent on the right

  const today = $derived(new Date());
  const todayStr = $derived(format(today, "yyyy-MM-dd"));

  $effect(() => {
    if (!endPickerValue) {
      endPickerValue = todayStr;
      nightIndex = 6;
    }
  });

  const clampedEndDay = $derived.by(() => {
    const d = endPickerValue ? new Date(endPickerValue + 'T00:00:00') : new Date();
    if (Number.isNaN(d.getTime())) return today;
    return d > today ? today : d;
  });

  const windowStart = $derived(subDays(clampedEndDay, 6));
  const windowEnd = $derived(clampedEndDay);
  const rangeLabel = $derived(`${format(windowStart, "MMM d")} – ${format(windowEnd, "MMM d, yyyy")}`);
  const canGoForward = $derived(format(windowEnd, "yyyy-MM-dd") !== todayStr);

  $effect(() => {
    pageHeader.eyebrow = `${format(subDays(clampedEndDay, 1), 'EEE')} → ${format(clampedEndDay, 'EEE dd MMM')}`;
    pageHeader.prev = () => { endPickerValue = format(subDays(windowEnd, 1), 'yyyy-MM-dd'); nightIndex = 6; };
    pageHeader.next = () => { if (canGoForward) { endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd'); nightIndex = 6; } };
    pageHeader.canNext = canGoForward;
    pageHeader.add = () => (addSleepOpen = true);
    pageHeader.addLabel = 'Log sleep';
    return resetPageHeader;
  });

  // Map biometrics to nights array (filling in missing dates for the last 7 days)
  type NightMissing = {
    rawDate: string;
    date: string;
    label: string;
    day: string;
    missing: true;
    score: 0;
  };

  type NightData = {
    rawDate: string;
    date: string;
    label: string;
    day: string;
    missing: false;
    score: number;
    duration: string;
    durationRaw: number;
    inBed: string;
    inBedRaw: number;
    quality: "Optimal" | "Moderate" | "Poor";
    bedtime: string;
    wakeup: string;
    deep: number;
    rem: number;
    light: number;
    awake: number;
    stagesAvailable: boolean;
    awakeMins: number;
    hr: number;
    hrv: number;
    hrvZ: number | null;
    rhrZ: number | null;
    debt: number;
    need: number;
    periods: any[];
  };

  type Night = NightMissing | NightData;

  function isNightData(x: Night): x is NightData {
    return x.missing === false;
  }

  function buildNightDataFromBio(
    b: Record<string, any>,
    displayDateStr: string,
    dateLabel: string,
    shortLabel: string,
    dayLabel: string
  ): NightData | null {
    if (!b?.sleep_score && !b?.sleep_duration_min) return null;

    const h = Math.floor((b.sleep_duration_min || 0) / 60);
    const m = Math.round((b.sleep_duration_min || 0) % 60);
    const bedtime = b.sleep_bedtime ? new Date(b.sleep_bedtime) : null;
    const wakeup = b.sleep_wakeup ? new Date(b.sleep_wakeup) : null;
    const timeInBedMin =
      b.sleep_in_bed_min ||
      (bedtime && wakeup ? Math.round((wakeup.getTime() - bedtime.getTime()) / 60000) : 0);
    const inBedH = Math.floor(timeInBedMin / 60);
    const inBedM = timeInBedMin % 60;
    const hour12 = (athleteStore.profile as any)?.time_format !== "24h";

    const stagesAvailable =
      metricPresent(b.sleep_deep_pct) ||
      metricPresent(b.sleep_rem_pct) ||
      metricPresent(b.sleep_light_pct) ||
      metricPresent(b.sleep_awake_pct);

    const res: NightData = {
      rawDate: displayDateStr,
      date: dateLabel,
      label: shortLabel,
      day: dayLabel,
      missing: false,
      score: b.sleep_score || 0,
      duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
      durationRaw: b.sleep_duration_min || 0,
      inBed: timeInBedMin > 0 ? `${inBedH}h ${inBedM}m` : "0h 0m",
      inBedRaw: timeInBedMin,
      quality:
        (b.sleep_score || 0) >= 67
          ? "Optimal"
          : (b.sleep_score || 0) >= 34
            ? "Moderate"
            : "Poor",
      bedtime: bedtime
        ? bedtime.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12 })
        : "N/A",
      wakeup: wakeup
        ? wakeup.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12 })
        : "N/A",
      deep: b.sleep_deep_pct || 0,
      rem: b.sleep_rem_pct || 0,
      light: b.sleep_light_pct || 0,
      awake: b.sleep_awake_pct || 0,
      stagesAvailable,
      awakeMins: 0,
      hr: b.resting_hr || 0,
      hrv: b.hrv_rmssd || 0,
      hrvZ: typeof b.hrv_z === "number" && Number.isFinite(b.hrv_z) ? Number(b.hrv_z) : null,
      rhrZ: typeof b.rhr_z === "number" && Number.isFinite(b.rhr_z) ? Number(b.rhr_z) : null,
      debt: b.sleep_debt_min || 0,
      need: b.sleep_need_min || 480,
      periods: (b.periods || []).map((p: any) => {
        const pStart = new Date(p.started_at);
        const pEnd = new Date(p.ended_at);
        const pInBedMin = p.in_bed_min || Math.round((pEnd.getTime() - pStart.getTime()) / 60000);
        const pAwakeMins = Math.round((pInBedMin * (p.awake_pct || 0)) / 100);
        const pSleepMins = Math.max(0, pInBedMin - pAwakeMins);
        return {
          ...p,
          label: p.is_nap ? "Nap" : "Main Sleep",
          timeRange: `${pStart.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12 })} – ${pEnd.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12 })}`,
          duration: `${Math.floor(pSleepMins / 60)}h ${pSleepMins % 60}m`,
          durationRaw: pSleepMins,
          inBed: `${Math.floor(pInBedMin / 60)}h ${pInBedMin % 60}m`,
          inBedRaw: pInBedMin,
          awakeMins: pAwakeMins,
          deep: p.deep_pct || 0,
          rem: p.rem_pct || 0,
          light: p.light_pct || 0,
          awake: p.awake_pct || 0
        };
      })
    };

    const aggInBed = res.periods.reduce((sum: number, p: any) => sum + p.inBedRaw, 0);
    if (aggInBed > res.inBedRaw) {
      res.inBedRaw = aggInBed;
      res.inBed = `${Math.floor(aggInBed / 60)}h ${aggInBed % 60}m`;
    }
    res.awakeMins = Math.round((res.inBedRaw * (res.awake || 0)) / 100);
    return res;
  }

  const nights = $derived.by<Night[]>(() => {
    // Build oldest→newest for display (today on the right).
    const asc = Array.from({ length: 7 }, (_, i) => {
      const d = addDays(windowStart, i);
      const displayDateStr = format(d, "yyyy-MM-dd");

      // In this UI, the selector day represents the **wake day** (the morning you wake up).
      // Biometrics sleep rows are stored under that same date, so we match 1:1.
      const b = athleteStore.biometrics?.series?.find(
        (s: any) => s.date === displayDateStr,
      );

      const isToday = displayDateStr === todayStr;
      const dateLabel = isToday ? "Today" : format(d, "MMM d");
      const shortLabel = format(d, "MMM d");
      const dow = format(d, "EE");
      const dayLabel = dow === "Thu" ? "Th" : dow.charAt(0);
      if (!b || (!b.sleep_score && !b.sleep_duration_min)) {
        return {
          date: dateLabel,
          label: shortLabel,
          day: dayLabel,
          rawDate: displayDateStr,
          missing: true,
          score: 0,
        } satisfies NightMissing;
      }

      const h = Math.floor((b.sleep_duration_min || 0) / 60);
      const m = Math.round((b.sleep_duration_min || 0) % 60);

      const bedtime = b.sleep_bedtime ? new Date(b.sleep_bedtime) : null;
      const wakeup = b.sleep_wakeup ? new Date(b.sleep_wakeup) : null;
      const timeInBedMin = b.sleep_in_bed_min || (bedtime && wakeup ? Math.round((wakeup.getTime() - bedtime.getTime()) / 60000) : 0);
      const inBedH = Math.floor(timeInBedMin / 60);
      const inBedM = timeInBedMin % 60;

      const stagesAvailable =
        metricPresent(b.sleep_deep_pct) ||
        metricPresent(b.sleep_rem_pct) ||
        metricPresent(b.sleep_light_pct) ||
        metricPresent(b.sleep_awake_pct);

      const res: NightData = {
        date: dateLabel,
        label: shortLabel,
        day: dayLabel,
        rawDate: displayDateStr,
        score: b.sleep_score || 0,
        duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
        durationRaw: b.sleep_duration_min || 0,
        inBed: timeInBedMin > 0 ? `${inBedH}h ${inBedM}m` : "0h 0m",
        inBedRaw: timeInBedMin,
        quality:
          (b.sleep_score || 0) >= 67
            ? "Optimal"
            : (b.sleep_score || 0) >= 34
              ? "Moderate"
              : "Poor",
        bedtime: bedtime
          ? bedtime.toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
              hour12: (athleteStore.profile as any)?.time_format !== '24h',
            })
          : "N/A",
        wakeup: wakeup
          ? wakeup.toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
              hour12: (athleteStore.profile as any)?.time_format !== '24h',
            })
          : "N/A",
        deep: b.sleep_deep_pct || 0,
        rem: b.sleep_rem_pct || 0,
        light: b.sleep_light_pct || 0,
        awake: b.sleep_awake_pct || 0,
        stagesAvailable,
        awakeMins: 0,
        hr: b.resting_hr || 0,
        hrv: b.hrv_rmssd || 0,
        hrvZ: typeof b.hrv_z === 'number' && Number.isFinite(b.hrv_z) ? Number(b.hrv_z) : null,
        rhrZ: typeof b.rhr_z === 'number' && Number.isFinite(b.rhr_z) ? Number(b.rhr_z) : null,
        debt: b.sleep_debt_min || 0,
        need: b.sleep_need_min || 480,
        periods: (b.periods || []).map((p: any) => {
          const pStart = new Date(p.started_at);
          const pEnd = new Date(p.ended_at);
          const pInBedMin = p.in_bed_min || Math.round((pEnd.getTime() - pStart.getTime()) / 60000);
          const pAwakeMins = Math.round((pInBedMin * (p.awake_pct || 0)) / 100);
          const pSleepMins = Math.max(0, pInBedMin - pAwakeMins);
          
          return {
            ...p,
            label: p.is_nap ? "Nap" : "Main Sleep",
            timeRange: `${pStart.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: (athleteStore.profile as any)?.time_format !== '24h' })} – ${pEnd.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: (athleteStore.profile as any)?.time_format !== '24h' })}`,
            duration: `${Math.floor(pSleepMins / 60)}h ${pSleepMins % 60}m`,
            durationRaw: pSleepMins,
            inBed: `${Math.floor(pInBedMin / 60)}h ${pInBedMin % 60}m`,
            inBedRaw: pInBedMin,
            awakeMins: pAwakeMins,
            deep: p.deep_pct || 0,
            rem: p.rem_pct || 0,
            light: p.light_pct || 0,
            awake: p.awake_pct || 0,
          };
        }),
        missing: false,
      };

      // Aggregating Time in Bed from periods to ensure consistency if naps exist
      const aggInBed = res.periods.reduce((sum: number, p: any) => sum + p.inBedRaw, 0);
      if (aggInBed > res.inBedRaw) {
        res.inBedRaw = aggInBed;
        res.inBed = `${Math.floor(aggInBed / 60)}h ${aggInBed % 60}m`;
      }

      // Keep `awakeMins` consistent for the "whole night" row too.
      const wholeAwakeMins = Math.round((res.inBedRaw * (res.awake || 0)) / 100);
      res.awakeMins = wholeAwakeMins;

      return res;
    });
    return asc;
  });

  $effect(() => {
    // Default to most recent day in the window and clamp.
    nightIndex = Math.max(0, Math.min(6, nightIndex ?? 0));
  });

  const n = $derived<Night>(nights[nightIndex] || nights[0]);
  const current = $derived(
    currentRecoveryState(
      athleteStore.biometrics?.series,
      athleteStore.profile?.timezone_offset_min
    )
  );

  const nightData = $derived.by<NightData | null>(() => {
    if (n && isNightData(n)) return n;
    if (n?.rawDate === todayStr && current.row) {
      return buildNightDataFromBio(
        current.row,
        todayStr,
        "Today",
        format(new Date(), "MMM d"),
        n.day
      );
    }
    return null;
  });

  const carryOverLabel = $derived.by(() => {
    if (n?.rawDate !== todayStr || !current.row || current.hasTodayRow) return null;
    if (isNightData(n)) return null;
    if (current.ageHours !== null && current.ageHours < 36) return "Carried over from last night";
    if (current.date) {
      try {
        return `Carried over from ${format(new Date(current.date + "T12:00:00"), "MMM d")}`;
      } catch {
        return "Carried over from previous night";
      }
    }
    return "Carried over from previous night";
  });
  const avg7d = $derived.by(() => {
    const vals = nights.map((x) => Number(x.score)).filter((v) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  });

  // Stage colors are categorical (deep/rem/light/awake), not bounded scores
  // — they encode a *category* of sleep architecture, so they're allowed to
  // stay distinct and are not driven by the semantic ASTRAPHE rules.
  const stageColors: Record<string, string> = {
    deep: 'var(--blue)',
    rem: 'var(--teal)',
    light: 'var(--amber)',
    awake: 'var(--red)',
  };
  // Sleep score is a bounded 0-100 score so it follows the unified rule of
  // thirds (>=67 teal / 34-66 amber / <=33 red).
  let scoreColor = $derived(
    current.isStale && n?.rawDate === todayStr
      ? "var(--text2)"
      : boundedScoreCssColor(nightData?.score ?? n.score)
  );
  const getSleepColor = (score: number) => boundedScoreCssColor(score);

  // Allow deep-linking to a specific day, e.g. /sleep?day=2026-04-22
  let lastAppliedDay = $state<string | null>(null);
  onMount(() => {
    const unsub = page.subscribe(($p) => {
      const day = $p.url.searchParams.get("day");
      if (!day || day === lastAppliedDay) return;
      lastAppliedDay = day;
      endPickerValue = day;
      nightIndex = 6;
    });
    return unsub;
  });

  let addSleepOpen = $state(false);

  async function handleSleepSaved(payload: object) {
    await athleteStore.addSleep(payload);
  }

  let selectedPeriod = $state<any>(null);
  let showPeriodModal = $state(false);

  function openPeriodDetails(period: any) {
    selectedPeriod = period;
    showPeriodModal = true;
  }

  let analysisText = $state<string | null>(null);
  let analysisLoading = $state(false);
  let activeAnalysisKey: string | null = null;
  $effect(() => {
    void analysisNavEpoch.epoch;
    const scopeKey = n?.rawDate;
    if (!scopeKey) {
      analysisText = null;
      return;
    }

    const cached = sleepAnalysisMemo.get(scopeKey);
    if (cached !== undefined) {
      analysisText = cached;
      return;
    }

    analysisText = null;
    const requestKey = `sleep-analysis:${scopeKey}`;
    activeAnalysisKey = requestKey;

    (async () => {
      try {
        analysisLoading = true;
        const res = await api.get<{ analysis: { content: string } }>(`/v1/analysis/sleep?day=${scopeKey}`);
        const content = typeof res?.analysis?.content === "string" ? res.analysis.content.trim() : "";
        if (activeAnalysisKey !== requestKey) return;
        const next = content || null;
        sleepAnalysisMemo.set(scopeKey, next);
        analysisText = next;
      } catch {
        if (activeAnalysisKey !== requestKey) return;
        sleepAnalysisMemo.set(scopeKey, null);
      } finally {
        if (activeAnalysisKey === requestKey) analysisLoading = false;
      }
    })();
  });
</script>

<AddSleepModal
  show={addSleepOpen}
  onClose={() => (addSleepOpen = false)}
  onSaved={handleSleepSaved}
/>

<div class="flex flex-col gap-3.5">
  {#if !isConnected}
    <EmptyState title="No Sleep Data" message="Connect WHOOP, Garmin, or Apple Health to track your sleep architecture and recovery." icon="🌙" secondaryLabel="Log Sleep" onSecondaryAction={() => (addSleepOpen = true)} />
  {:else if !hasData}
    <EmptyState title="Waiting for Sleep Sync" message="We'll analyze your sleep as soon as your device syncs with our servers." icon="⏳" />
  {:else if !nightData}
    <section class="bg-bg2 border border-dashed border-border rounded-[24px] p-6 text-center">
      <p class="m-0 text-[14px] font-semibold mb-1">No sleep data for {n?.date}</p>
      <p class="m-0 text-[12px] text-text2">We couldn't find a sleep record for this night.</p>
    </section>
  {:else}
    {@const effPct = nightData.inBedRaw > 0 ? Math.round((nightData.durationRaw / nightData.inBedRaw) * 100) : null}
    <!-- Score -->
    <section aria-label="Sleep score" class="bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex gap-[18px] items-center">
      <div class="relative w-[112px] h-[112px] shrink-0">
        <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true" class="block -rotate-90">
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--border)" stroke-width="8"></circle>
          <circle cx="56" cy="56" r="48" fill="none" stroke={scoreColor} stroke-width="8" stroke-linecap="round" stroke-dasharray="{(Math.min(nightData.score, 100) / 100) * 301.6} 302"></circle>
        </svg>
        <div class="absolute inset-0 flex items-center justify-center"><span class="font-display text-[42px] leading-none">{nightData.score}</span></div>
      </div>
      <dl class="m-0 flex-1 grid grid-cols-2 gap-3">
        <div><dt class="text-[11px] text-text2">Asleep</dt><dd class="m-0 text-[17px] font-medium">{nightData.duration}</dd></div>
        <div><dt class="text-[11px] text-text2">In bed</dt><dd class="m-0 text-[17px] font-medium">{nightData.inBed}</dd></div>
        <div><dt class="text-[11px] text-text2">Efficiency</dt><dd class="m-0 text-[17px] font-medium">{effPct === null ? '--' : `${effPct}%`}</dd></div>
        <div><dt class="text-[11px] text-text2">Debt</dt><dd class="m-0 text-[17px] font-medium" style="color: {sleepDebtCssColor(nightData.debt)}">{formatHoursMinutesFromMinutes(nightData.debt)}</dd></div>
      </dl>
    </section>

    <!-- Stages -->
    <section aria-label="Sleep stages" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-[22px]">Stages</h2>
        <span class="font-mono text-[11px] text-text2">{nightData.bedtime} → {nightData.wakeup}</span>
      </div>
      {#if nightData.stagesAvailable}
        <div aria-hidden="true" class="flex gap-[3px] h-2.5">
          {#each [['deep', nightData.deep], ['rem', nightData.rem], ['light', nightData.light], ['awake', nightData.awake]] as [k, v] (k)}
            <span class="rounded-[3px]" style="flex: {Math.max(Number(v), 1)} 1 0; background: {stageColors[k as string]}"></span>
          {/each}
        </div>
        <div class="grid grid-cols-4 gap-2">
          {#each [
            { key: 'awake', name: 'Awake', pct: nightData.awake, mins: nightData.awakeMins },
            { key: 'light', name: 'Light', pct: nightData.light, mins: Math.round((nightData.inBedRaw * nightData.light) / 100) },
            { key: 'deep', name: 'Deep', pct: nightData.deep, mins: Math.round((nightData.inBedRaw * nightData.deep) / 100) },
            { key: 'rem', name: 'REM', pct: nightData.rem, mins: Math.round((nightData.inBedRaw * nightData.rem) / 100) }
          ] as s (s.key)}
            <div class="flex flex-col gap-[3px]">
              <span class="flex items-center gap-1.5 text-[11px] text-text2"><span aria-hidden="true" class="w-2 h-2 rounded-[2px]" style="background: {stageColors[s.key]}"></span>{s.name}</span>
              <span class="text-[15px] font-medium">{formatHoursMinutesFromMinutes(s.mins)}</span>
              <span class="font-mono text-[11px] text-text2">{Math.round(s.pct)}%</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="m-0 text-[13px] leading-[1.45] text-text2">This source gave duration and score but no REM/deep/light/awake breakdown.</p>
      {/if}
    </section>

    {#if nightData.periods && nightData.periods.length > 1}
      <section aria-label="Sleep sessions" class="flex flex-col gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">SESSIONS</span>
        {#each nightData.periods as period (period?.id ?? period?.started_at ?? period?.ended_at ?? period?.label)}
          <button type="button" class="flex items-center justify-between px-4 py-3 rounded-[18px] bg-bg1 border border-border text-left w-full cursor-pointer" onclick={() => openPeriodDetails(period)}>
            <span class="flex flex-col gap-0.5"><span class="text-[14px] font-medium">{period.label}</span><span class="font-mono text-[11px] text-text2">{period.timeRange}</span></span>
            <span class="font-mono text-[12px] text-text1">{period.duration}</span>
          </button>
        {/each}
      </section>
    {/if}

    <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-border">
      <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">TIP</span>
      <span class="text-[13px] leading-[1.45] text-text1">
        {#if analysisLoading && analysisText === null}Analyzing…{:else}
          {analysisText ??
            (!nightData.stagesAvailable
              ? 'Stage data is unavailable for this night, so this is based on duration, debt, HRV and resting HR.'
              : nightData.deep < 15
                ? 'Deep sleep is below your baseline. Cool the room and cut screens before bed tonight.'
                : nightData.rem < 20
                  ? 'REM is slightly low, which can affect cognitive performance today.'
                  : 'Your sleep architecture looks balanced. Recovery is on track.')}
        {/if}
      </span>
    </div>
  {/if}
</div>

<Modal
  show={showPeriodModal}
  title={selectedPeriod?.label || "Sleep Details"}
  onClose={() => (showPeriodModal = false)}
>
  {#if selectedPeriod}
    <div class="flex flex-col gap-6">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-[22px] font-bold">{selectedPeriod.duration}</p>
          <p class="text-[10px] text-text2 font-mono uppercase tracking-widest">Time Asleep</p>
          
          <div class="mt-2">
            <p class="text-[16px] font-semibold text-text1">{selectedPeriod.inBed}</p>
            <p class="text-[9px] text-text2 font-mono uppercase tracking-widest">Time in Bed</p>
          </div>
          
          <p class="text-[10px] text-text2 font-mono uppercase mt-3">{selectedPeriod.timeRange}</p>
        </div>
        {#if selectedPeriod.score}
          <RadialProgress
            value={selectedPeriod.score}
            max={100}
            size={64}
            color={getSleepColor(selectedPeriod.score)}
            label={selectedPeriod.score.toString()}
            sub="SCORE"
          />
        {/if}
      </div>

      <div class="flex flex-col gap-4">
        <p class="text-[13px] font-semibold">Stage Breakdown</p>
        <div class="flex h-6 rounded-lg overflow-hidden gap-0.5">
          {#each [["deep", selectedPeriod.deep], ["rem", selectedPeriod.rem], ["light", selectedPeriod.light], ["awake", selectedPeriod.awake]] as [k, v] (k)}
            <div
              style="flex: {v || 1}; background: {stageColors[k as string]}"
            ></div>
          {/each}
        </div>

        <div class="grid grid-cols-2 gap-3">
          {#each [{ key: "deep", label: "Deep", pct: selectedPeriod.deep, mins: Math.round((selectedPeriod.inBedRaw * selectedPeriod.deep) / 100) }, { key: "rem", label: "REM", pct: selectedPeriod.rem, mins: Math.round((selectedPeriod.inBedRaw * selectedPeriod.rem) / 100) }, { key: "light", label: "Light", pct: selectedPeriod.light, mins: Math.round((selectedPeriod.inBedRaw * selectedPeriod.light) / 100) }, { key: "awake", label: "Awake", pct: selectedPeriod.awake, mins: selectedPeriod.awakeMins }] as s (s.key)}
            <div class="p-3 rounded-xl bg-glass border border-border/50">
              <div class="flex items-center gap-2 mb-1">
                <div class="w-2 h-2 rounded-full" style="background: {stageColors[s.key]}"></div>
                <span class="text-xs font-medium text-text1">{s.label}</span>
              </div>
              <div class="flex items-baseline gap-1.5">
                <span class="text-lg font-bold" style="color: {stageColors[s.key]}">{s.pct}%</span>
                <span class="text-[10px] text-text2 font-mono">{formatHoursMinutesFromMinutes(s.mins)}</span>
              </div>
            </div>
          {/each}
        </div>
      </div>

      {#if selectedPeriod.is_nap}
        <div class="p-4 rounded-xl bg-blue/5 border border-blue/20">
          <p class="text-[12px] text-blue font-semibold mb-1">💡 Coaching Tip</p>
          <p class="text-[11px] text-text1 leading-relaxed">
            Naps contribute to your total recovery but can interfere with nighttime sleep if taken too late in the day.
          </p>
        </div>
      {/if}
    </div>
  {/if}
</Modal>
