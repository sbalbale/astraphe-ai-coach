<script module lang="ts">
  import { SvelteMap } from 'svelte/reactivity';

  const sleepAnalysisMemo = new SvelteMap<string, string | null>();
</script>

<script lang="ts">
  import Card from "$lib/components/Card.svelte";
  import Tag from "$lib/components/Tag.svelte";
  import EmptyStateCard from "$lib/components/ui/EmptyStateCard.svelte";
  import { goto } from "$app/navigation";
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
  import { onMount, untrack } from "svelte";
  import { stageMinutes } from "$lib/utils/sleepStages";
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { bodyDate, rememberBodyDate } from '$lib/stores/bodyDate.svelte';
  import { page } from "$app/stores";
  import AddSleepModal from "$lib/components/AddSleepModal.svelte";
  import { viewport } from '$lib/stores/viewport.svelte';
  import { bodyEyebrow } from '$lib/utils/bodyWide';
  import BodyScoreTabs from '$lib/components/wide/body/BodyScoreTabs.svelte';
  import SleepWide from '$lib/components/wide/body/SleepWide.svelte';

  const isConnected = $derived(
    Object.values(athleteStore.syncStatus?.integrations || {}).some(
      (i: any) => i.connected,
    ),
  );
  const hasData = $derived(athleteStore.biometrics?.series?.length > 0);
  // "Connect an app" only when we *know* nothing is connected and there's no data:
  // manual-only athletes (logged sleep/workouts) see their data, and connected users
  // don't flash this while the sync status is still loading.
  const showConnectPrompt = $derived(athleteStore.syncStatus != null && !isConnected && !hasData);

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
  let endPickerValue = $state(bodyDate.value ?? "");
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
  // Load older biometrics when this view reaches back past what's loaded (the store starts with
  // the newest 200 workouts / 60 days of biometrics).
  $effect(() => {
    const day = format(subDays(windowStart, 7), 'yyyy-MM-dd');
    untrack(() => {
      void athleteStore.ensureBiometricsFrom(day);
    });
  });

  const windowEnd = $derived(clampedEndDay);
  const rangeLabel = $derived(`${format(windowStart, "MMM d")} – ${format(windowEnd, "MMM d, yyyy")}`);
  const canGoForward = $derived(format(windowEnd, "yyyy-MM-dd") !== todayStr);
  /** The day picked in the 7-day strip; the header shows it. */
  const selectedDayStr = $derived(format(addDays(windowStart, nightIndex), 'yyyy-MM-dd'));

  $effect(() => {
    // Prev / next step the picked day; past either end of the 7-day strip, the strip moves.
    pageHeader.prev = () => { if (nightIndex > 0) nightIndex -= 1; else { endPickerValue = format(subDays(windowStart, 1), 'yyyy-MM-dd'); nightIndex = 6; } };
    pageHeader.next = () => { if (nightIndex < 6) nightIndex += 1; else if (canGoForward) { endPickerValue = format(addDays(windowEnd, 1), 'yyyy-MM-dd'); nightIndex = 6; } };
    pageHeader.canNext = selectedDayStr !== todayStr;
    pageHeader.today = () => { endPickerValue = todayStr; nightIndex = 6; };
    pageHeader.dateMax = todayStr;
    pageHeader.dateLabel = selectedDayStr === todayStr ? 'Today' : format(addDays(windowStart, nightIndex), 'EEE d MMM');
    pageHeader.dateMarks = (athleteStore.biometrics?.series ?? []).filter((r: any) => r?.date && (Number(r?.sleep_duration_min) > 0 || Number(r?.sleep_score) > 0)).map((r: any) => r.date);
    pageHeader.dateValue = selectedDayStr;
    // Wide layouts show Recovery, Sleep and Strain as one "Body" screen.
    const wideDay = nights[nightIndex]?.rawDate ?? todayStr;
    pageHeader.wideTitle = 'Body';
    pageHeader.wideEyebrow = bodyEyebrow(wideDay, (athleteStore.biometrics?.series ?? []).find((r: any) => r?.date === wideDay) ?? (current.row as any));
    return resetPageHeader;
  });

  // Share the picked day with the other Body sub-tabs (Recovery / Sleep / Strain).
  $effect(() => {
    rememberBodyDate(format(addDays(windowStart, nightIndex), "yyyy-MM-dd"), todayStr);
  });

  // The header calendar writes pageHeader.dateValue; follow it.
  $effect(() => {
    // Runs only when the calendar writes (not when a day in the strip is picked).
    const picked = pageHeader.dateValue;
    if (picked && picked !== untrack(() => selectedDayStr) && picked <= todayStr) { endPickerValue = picked; nightIndex = 6; }
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
    /** null = no score for this night (e.g. a manual entry): shown as "--", not a red 0. */
    score: number | null;
    duration: string;
    durationRaw: number;
    inBed: string;
    inBedRaw: number;
    quality: "Optimal" | "Moderate" | "Poor" | null;
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
    debt: number | null;
    need: number | null;
    periods: any[];
    stageSegments: { stage: string; start_at: string; end_at: string }[];
  };

  type Night = NightMissing | NightData;

  function sleepQuality(score: unknown): NightData["quality"] {
    const v = Number(score);
    if (!(v > 0)) return null;
    return v >= 67 ? "Optimal" : v >= 34 ? "Moderate" : "Poor";
  }

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
      score: Number(b.sleep_score) > 0 ? Number(b.sleep_score) : null,
      duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
      durationRaw: b.sleep_duration_min || 0,
      inBed: timeInBedMin > 0 ? `${inBedH}h ${inBedM}m` : "0h 0m",
      inBedRaw: timeInBedMin,
      quality: sleepQuality(b.sleep_score),
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
      debt: Number.isFinite(Number(b.sleep_debt_min)) && b.sleep_debt_min != null ? Number(b.sleep_debt_min) : null,
      need: Number(b.sleep_need_min) > 0 ? Number(b.sleep_need_min) : null,
      stageSegments: b.stage_segments || [],
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
        score: Number(b.sleep_score) > 0 ? Number(b.sleep_score) : null,
        duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
        durationRaw: b.sleep_duration_min || 0,
        inBed: timeInBedMin > 0 ? `${inBedH}h ${inBedM}m` : "0h 0m",
        inBedRaw: timeInBedMin,
        quality: sleepQuality(b.sleep_score),
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
        debt: Number.isFinite(Number(b.sleep_debt_min)) && b.sleep_debt_min != null ? Number(b.sleep_debt_min) : null,
        need: Number(b.sleep_need_min) > 0 ? Number(b.sleep_need_min) : null,
        stageSegments: b.stage_segments || [],
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
    deep: 'var(--stage-deep)',
    light: 'var(--stage-light)',
    rem: 'var(--violet)',
    awake: 'var(--text2)',
  };

  // Hypnogram rows, top to bottom (design order): awake, REM, light, deep.
  const HYP_W = 314;
  const HYP_ROW_Y: Record<string, number> = { awake: 12, rem: 36, light: 60, deep: 84 };
  function buildHypnogram(segs: { stage: string; start_at: string; end_at: string }[]) {
    const parsed = segs
      .map((x) => ({ stage: x.stage, a: Date.parse(x.start_at), b: Date.parse(x.end_at) }))
      .filter((x) => Number.isFinite(x.a) && Number.isFinite(x.b) && x.b > x.a && x.stage in HYP_ROW_Y);
    if (parsed.length < 2) return null;
    const t0 = parsed[0].a;
    const span = parsed[parsed.length - 1].b - t0;
    if (span <= 0) return null;
    const px = (t: number) => Math.round(((t - t0) / span) * HYP_W * 10) / 10;
    const bars = parsed.map((x) => ({ x1: px(x.a), x2: Math.max(px(x.b), px(x.a) + 1), y: HYP_ROW_Y[x.stage], stage: x.stage }));
    const path = bars.map((bar, i) => (i === 0 ? `M${bar.x1},${bar.y}` : `L${bar.x1},${bar.y}`) + ` L${bar.x2},${bar.y}`).join(' ');
    return { bars, path };
  }
  // Sleep score is a bounded 0-100 score so it follows the unified rule of
  // thirds (>=67 teal / 34-66 amber / <=33 red).
  let scoreColor = $derived(
    current.isStale && n?.rawDate === todayStr
      ? "var(--text2)"
      : (nightData ? nightData.score : n.score) == null
        ? "var(--text2)"
        : boundedScoreCssColor((nightData ? nightData.score : n.score) as number)
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
  // Deep link from Today's "Log sleep myself": /sleep?log=1 opens the form once.
  onMount(() => {
    if ($page.url.searchParams.get('log') === '1') addSleepOpen = true;
  });

  /** "Sun → Mon" for the night ending on the given wake day. */
  function nightLabel(rawDate: string | undefined): string {
    if (!rawDate) return 'this night';
    const wake = parseISO(rawDate);
    return `${format(subDays(wake, 1), 'EEE')} → ${format(wake, 'EEE')}`;
  }
  const avgSleepMin7d = $derived.by(() => {
    const vals = nights.filter(isNightData).map((x) => x.durationRaw).filter((v) => v > 0);
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
  });
  const maxNightMin = $derived(Math.max(540, ...nights.filter(isNightData).map((x) => x.durationRaw)));

  let checking = $state(false);
  /** Re-read from our server: shows synced sleep if it has arrived. */
  async function checkSync() {
    checking = true;
    try {
      await athleteStore.fetchAll(true);
    } finally {
      checking = false;
    }
  }

  async function handleSleepSaved(payload: object) {
    await athleteStore.addSleep(payload);
  }

  const hour12 = $derived((athleteStore.profile as any)?.time_format !== '24h');
  const wideTip = $derived.by<string | null>(() => {
    if (!nightData) return null;
    if (analysisLoading && analysisText === null) return 'Analyzing…';
    return (
      analysisText ??
      (!nightData.stagesAvailable
        ? 'Stage data is unavailable for this night, so this is based on duration, debt, HRV and resting HR.'
        : nightData.deep < 15
          ? 'Deep sleep is below your baseline. Cool the room and cut screens before bed tonight.'
          : nightData.rem < 20
            ? 'REM is slightly low, which can affect cognitive performance today.'
            : 'Your sleep architecture looks balanced. Recovery is on track.')
    );
  });

  // Naps for the selected night (the main sleep is already the page's subject).
  const naps = $derived(((nightData?.periods ?? []) as any[]).filter((p) => p?.is_nap));

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
  /** Stage minutes that add up to the night (light / deep / REM split the time asleep). */
  const stageMins = $derived(
    nightData ? stageMinutes(nightData.inBedRaw, nightData.durationRaw, nightData) : { awake: 0, light: 0, deep: 0, rem: 0 }
  );
</script>

<AddSleepModal
  show={addSleepOpen}
  onClose={() => (addSleepOpen = false)}
  onSaved={handleSleepSaved}
/>

{#if viewport.wide && !showConnectPrompt && hasData}
  <div class="flex-1 flex flex-col gap-[22px]">
    <BodyScoreTabs active="sleep" day={n?.rawDate ?? todayStr} />
    <SleepWide
      night={nightData}
      {nights}
      selected={nightIndex}
      onSelect={(i) => (nightIndex = i)}
      title={n?.rawDate === todayStr ? 'Last night' : nightLabel(n?.rawDate)}
      tip={wideTip}
      {hour12}
      onLog={() => (addSleepOpen = true)}
      onCheckSync={checkSync}
      {checking}
      emptyTitle={`No sleep for ${nightLabel(n?.rawDate)} yet`}
    />
  </div>
{:else}
<div class="flex flex-col gap-3.5">
  {#if showConnectPrompt}
    <EmptyStateCard
      icon="link"
      tone="blue"
      eyebrow="Not set up"
      title="Track your sleep"
      message="Sleep comes from a wearable worn to bed — WHOOP or a Garmin watch. You can also log nights by hand."
      actionLabel="Connect a wearable"
      onAction={() => goto('/profile/connections')}
      secondaryLabel="Log sleep"
      onSecondary={() => (addSleepOpen = true)}
    />
  {:else if !hasData}
    <EmptyStateCard
      icon="moon"
      tone="amber"
      eyebrow="Waiting for sync"
      title="No sleep yet"
      message="Your wearable is connected. Nights appear here after its first sync, usually within 30 minutes of waking."
      actionLabel="Log sleep"
      onAction={() => (addSleepOpen = true)}
      secondaryLabel={checking ? 'Checking…' : 'Check sync now'}
      onSecondary={checkSync}
    />
  {:else if !nightData}
    <EmptyStateCard
      icon="moon"
      tone="amber"
      eyebrow="Waiting for sync"
      title="No sleep for {nightLabel(n?.rawDate)} yet"
      message="Your watch may not have synced, or it wasn't worn that night. Synced sleep replaces anything you log by hand."
      actionLabel="Log sleep"
      onAction={() => (addSleepOpen = true)}
      secondaryLabel={checking ? 'Checking…' : 'Check sync now'}
      onSecondary={checkSync}
    />
    <section aria-label="Last 7 nights" class="bg-bg2 border border-border rounded-card px-6 py-6">
      <div class="flex items-baseline justify-between mb-5">
        <h2 class="m-0 font-display font-normal text-[28px] text-text0">Last 7 nights</h2>
        {#if avgSleepMin7d !== null}
          <span class="font-mono text-[12px] tracking-[0.12em] text-text2">AVG {Math.floor(avgSleepMin7d / 60)}H {avgSleepMin7d % 60}M</span>
        {/if}
      </div>
      <div class="flex items-end gap-2 h-[120px]">
        {#each nights as night, i (night.rawDate)}
          {@const mins = isNightData(night) ? night.durationRaw : 0}
          <button
            type="button"
            class="flex-1 h-full flex items-end bg-transparent border-0 p-0 cursor-pointer"
            aria-label="{night.label}: {mins > 0 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : 'no sleep recorded'}"
            aria-pressed={i === nightIndex}
            onclick={() => (nightIndex = i)}
          >
            {#if mins > 0}
              <span class="block w-full rounded-[10px] bg-blue/40" style="height: {Math.max(18, Math.min(100, (mins / maxNightMin) * 100))}%"></span>
            {:else}
              <span class="block w-full h-full rounded-[10px] border border-dashed {i === nightIndex ? 'border-amber/50' : 'border-border'}"></span>
            {/if}
          </button>
        {/each}
      </div>
      <div class="flex gap-2 mt-3">
        {#each nights as night, i (night.rawDate)}
          <span class="flex-1 text-center font-mono text-[12px] {i === nightIndex && !isNightData(night) ? 'text-amber' : 'text-text2'}">{night.day}</span>
        {/each}
      </div>
    </section>
  {:else}
    {@const effPct = nightData.inBedRaw > 0 ? Math.round((nightData.durationRaw / nightData.inBedRaw) * 100) : null}
    <!-- Score -->
    <section aria-label="Sleep score" class="bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex gap-[18px] items-center">
      <div class="relative w-[112px] h-[112px] shrink-0">
        <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true" class="block -rotate-90">
          <circle cx="56" cy="56" r="48" fill="none" stroke="var(--border)" stroke-width="8"></circle>
          <circle cx="56" cy="56" r="48" fill="none" stroke={scoreColor} stroke-width="8" stroke-linecap="round" stroke-dasharray="{(Math.min(nightData.score ?? 0, 100) / 100) * 301.6} 302"></circle>
        </svg>
        <div class="absolute inset-0 flex items-center justify-center"><span class="font-display text-[42px] leading-none">{nightData.score ?? '--'}</span></div>
      </div>
      <dl class="m-0 flex-1 grid grid-cols-2 gap-3">
        <div><dt class="text-[11px] text-text2">Asleep</dt><dd class="m-0 text-[17px] font-medium">{nightData.duration}</dd></div>
        <div><dt class="text-[11px] text-text2">In bed</dt><dd class="m-0 text-[17px] font-medium">{nightData.inBed}</dd></div>
        <div><dt class="text-[11px] text-text2">Efficiency</dt><dd class="m-0 text-[17px] font-medium">{effPct === null ? '--' : `${effPct}%`}</dd></div>
        <div><dt class="text-[11px] text-text2">Debt</dt><dd class="m-0 text-[17px] font-medium" style="color: {nightData.debt == null ? 'var(--text2)' : sleepDebtCssColor(nightData.debt)}">{nightData.debt == null ? '--' : formatHoursMinutesFromMinutes(nightData.debt)}</dd></div>
      </dl>
    </section>

    <!-- Stages -->
    <section aria-label="Sleep stages" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3">
      <div class="flex justify-between items-center">
        <h2 class="m-0 font-display font-normal text-[22px]">Stages</h2>
        <div class="flex items-center gap-3">
          <span class="font-mono text-[11px] text-text2">{nightData.bedtime} → {nightData.wakeup}</span>
          <button type="button" class="h-11 px-3.5 rounded-[14px] border border-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer" onclick={() => (addSleepOpen = true)}>+ Log</button>
        </div>
      </div>
      {#if nightData.stagesAvailable}
        {@const hyp = buildHypnogram(nightData.stageSegments)}
        {#if hyp}
          <svg viewBox="0 0 314 96" width="100%" height="96" role="img" aria-label="Sleep stage timeline" class="block">
            {#each [12, 36, 60, 84] as y (y)}<line x1="0" y1={y} x2="314" y2={y} stroke="var(--bg3)"></line>{/each}
            <path d={hyp.path} fill="none" stroke="var(--border)" stroke-width="1"></path>
            {#each hyp.bars as bar, i (i)}
              <line x1={bar.x1} y1={bar.y} x2={bar.x2} y2={bar.y} stroke={stageColors[bar.stage]} stroke-width="10" stroke-opacity={bar.stage === 'light' ? 0.7 : 1}></line>
            {/each}
          </svg>
        {:else}
        <div aria-hidden="true" class="flex gap-[3px] h-2.5">
          {#each [['deep', nightData.deep], ['rem', nightData.rem], ['light', nightData.light], ['awake', nightData.awake]] as [k, v] (k)}
            <span class="rounded-[3px]" style="flex: {Math.max(Number(v), 1)} 1 0; background: {stageColors[k as string]}"></span>
          {/each}
        </div>
        {/if}
        <div class="grid grid-cols-4 gap-2">
          {#each [
            { key: 'awake', name: 'Awake', pct: nightData.awake, mins: stageMins.awake },
            { key: 'light', name: 'Light', pct: nightData.light, mins: stageMins.light },
            { key: 'deep', name: 'Deep', pct: nightData.deep, mins: stageMins.deep },
            { key: 'rem', name: 'REM', pct: nightData.rem, mins: stageMins.rem }
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

    {#if naps.length}
      <section aria-label="Naps" class="flex flex-col gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">{naps.length > 1 ? 'NAPS' : 'NAP'}</span>
        {#each naps as nap (nap?.id ?? nap?.started_at)}
          <div class="flex items-center justify-between px-4 py-3 rounded-[18px] bg-bg1 border border-border">
            <span class="font-mono text-[12px] text-text2">{nap.timeRange}</span>
            <span class="font-mono text-[13px] text-text0">{nap.duration}</span>
          </div>
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
{/if}
