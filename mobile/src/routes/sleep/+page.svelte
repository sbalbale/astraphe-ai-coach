<script lang="ts">
  import Card from "$lib/components/Card.svelte";
  import MetricBadge from "$lib/components/MetricBadge.svelte";
  import Tag from "$lib/components/Tag.svelte";
  import Pill from "$lib/components/Pill.svelte";
  import RadialProgress from "$lib/components/RadialProgress.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import DatePicker from "$lib/components/DatePicker.svelte";
  import LineChart from "$lib/components/charts/LineChart.svelte";
  import { athleteStore } from "$lib/stores/athleteStore.svelte";
  import { addDays, format, parseISO, subDays } from "date-fns";
  import { calculateSleepScore } from "$lib/utils/biometrics";

  const isConnected = $derived(
    Object.values(athleteStore.syncStatus?.integrations || {}).some(
      (i: any) => i.connected,
    ),
  );
  const hasData = $derived(athleteStore.biometrics?.series?.length > 0);

  // Rolling 7-day window (cannot go into the future).
  // Source of truth for the picker is a YYYY-MM-DD string.
  let endPickerValue = $state("");
  let nightIndex = $state(0); // most recent on the left

  const today = $derived(new Date());
  const todayStr = $derived(format(today, "yyyy-MM-dd"));

  $effect(() => {
    if (!endPickerValue) endPickerValue = todayStr;
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

  // Map biometrics to nights array (filling in missing dates for the last 7 days)
  let nights = $derived.by(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = subDays(windowEnd, i);
      const displayDateStr = format(d, "yyyy-MM-dd");

      // In this UI, the selector day represents the **wake day** (the morning you wake up).
      // Biometrics sleep rows are stored under that same date, so we match 1:1.
      const b = athleteStore.biometrics?.series?.find(
        (s: any) => s.date === displayDateStr,
      );

      const isToday = displayDateStr === todayStr;
      const dateLabel = isToday ? "Today" : format(d, "MMM d");
      const shortLabel = format(d, "MMM d");

      if (!b || (!b.sleep_score && !b.sleep_duration_min)) {
        return {
          date: dateLabel,
          label: shortLabel,
          rawDate: displayDateStr,
          missing: true,
          score: 0,
        };
      }

      const h = Math.floor((b.sleep_duration_min || 0) / 60);
      const m = Math.round((b.sleep_duration_min || 0) % 60);

      return {
        date: dateLabel,
        label: shortLabel,
        rawDate: displayDateStr,
        score: b.astrape_sleep_score || b.sleep_score || 0,
        duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
        durationRaw: b.sleep_duration_min || 0,
        quality:
          (b.astrape_sleep_score || b.sleep_score || 0) >= 67
            ? "Optimal"
            : (b.astrape_sleep_score || b.sleep_score || 0) >= 34
              ? "Moderate"
              : "Poor",
        bedtime: b.sleep_bedtime
          ? new Date(b.sleep_bedtime).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
              hour12: (athleteStore.profile as any)?.time_format !== '24h',
            })
          : "N/A",
        wakeup: b.sleep_wakeup
          ? new Date(b.sleep_wakeup).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
              hour12: (athleteStore.profile as any)?.time_format !== '24h',
            })
          : "N/A",
        deep: b.sleep_deep_pct || 0,
        rem: b.sleep_rem_pct || 0,
        light: b.sleep_light_pct || 0,
        awake: b.sleep_awake_pct || 0,
        hr: b.resting_hr || 0,
        hrv: b.hrv_rmssd || 0,
        debt: b.sleep_debt_min || 0,
        need: b.sleep_need_min || 480,
        periods: (b.periods || []).map((p: any) => ({
          ...p,
          label: p.is_nap ? "Nap" : "Main Sleep",
          timeRange: `${new Date(p.started_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: (athleteStore.profile as any)?.time_format !== '24h' })} – ${new Date(p.ended_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: (athleteStore.profile as any)?.time_format !== '24h' })}`,
          duration: `${Math.floor(p.duration_min / 60)}h ${p.duration_min % 60}m`
        })),
        missing: false,
      };
    });
  });

  $effect(() => {
    // Default to most recent day in the window and clamp.
    nightIndex = Math.max(0, Math.min(6, nightIndex ?? 0));
  });

  let n = $derived(nights[nightIndex] || nights[0]);

  const stageColors: Record<string, string> = {
    deep: "#4621FF",
    rem: "#00C8A8",
    light: "#FFCB88",
    awake: "#F07178",
  };
  let scoreColor = $derived(
    n
      ? n.score >= 67
        ? "#00C8A8"
        : n.score >= 34
          ? "#FFCB88"
          : "#F07178"
      : "var(--text2)",
  );

  const getSleepColor = (score: number) =>
    score >= 67 ? "#00C8A8" : score >= 34 ? "#FFCB88" : "#F07178";
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">
      Nightly Analysis
    </p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Sleep</h1>
  </div>

  {#if !isConnected}
    <EmptyState
      title="No Sleep Data"
      message="Connect WHOOP, Garmin, or Apple Health to track your sleep architecture and recovery."
      icon="🌙"
    />
  {:else if !hasData}
    <EmptyState
      title="Waiting for Sleep Sync"
      message="We'll analyze your sleep as soon as your device syncs with our servers."
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
          onclick={() => (endPickerValue = format(subDays(windowEnd, 7), "yyyy-MM-dd"))}
        >
          ←
        </button>
        <div class="w-[150px]">
          <DatePicker
            id="sleep-end"
            bind:value={endPickerValue}
            max={todayStr}
            ariaLabel="Select end day"
            buttonClass="h-8 px-2 pr-2 rounded-md border border-border bg-glass text-[12px] text-text0"
          />
        </div>
        <button
          type="button"
          class="h-8 px-2.5 rounded-md border border-border bg-glass text-text0 text-[12px]"
          aria-label="Jump to today"
          onclick={() => {
            endPickerValue = todayStr;
            nightIndex = 0;
          }}
        >
          Today
        </button>
        <button
          type="button"
          class="h-8 w-8 rounded-md border border-border bg-glass text-text0"
          aria-label="Next 7 days"
          disabled={!canGoForward}
          style={!canGoForward ? "opacity: 0.4; cursor: not-allowed;" : ""}
          onclick={() => {
            if (!canGoForward) return;
            endPickerValue = format(addDays(windowEnd, 7), "yyyy-MM-dd");
          }}
        >
          →
        </button>
      </div>
      <div class="text-[11px] text-text2 font-mono text-right">
        {rangeLabel}
      </div>
    </div>

    <!-- Night selector -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each nights as nt, i (nt.rawDate)}
        <Pill active={nightIndex === i} onclick={() => (nightIndex = i)}>
          {nt.date}
        </Pill>
      {/each}
    </div>

    <!-- Score card -->
    {#if n.missing}
      <Card style="border-style: dashed; opacity: 0.8;">
        <div class="flex flex-col items-center justify-center py-6 text-center">
          <span class="text-[32px] mb-2">🤷‍♂️</span>
          <p class="text-[14px] font-bold mb-1">No data for {n.date}</p>
          <p class="text-[11px] text-text2 max-w-[200px]">
            We couldn't find any sleep records for this night. Make sure your
            device synced.
          </p>
        </div>
      </Card>
    {:else}
      <Card
        style="background: {nightIndex === 0
          ? 'linear-gradient(135deg, rgba(70,33,255,0.15), rgba(0,200,168,0.08))'
          : 'var(--glass)'}; border-color: {nightIndex === 0
          ? 'rgba(70,33,255,0.25)'
          : 'var(--border)'}"
      >
        <div class="flex items-center gap-4">
          <RadialProgress
            value={n.score}
            max={100}
            size={72}
            color={scoreColor}
            label={n.score.toString()}
            sub="SLEEP"
          />
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-[18px] font-bold">{n.quality}</span>
              <Tag color={scoreColor}
                >{n.score >= 67
                  ? "OPTIMAL"
                  : n.score >= 34
                    ? "MODERATE"
                    : "POOR"}</Tag
              >
            </div>
            <p class="text-xs text-text1">{n.bedtime} → {n.wakeup}</p>
            <p class="text-[20px] font-bold mt-1" style="color: {scoreColor}">
              {n.duration}
              <span class="text-[12px] font-normal text-text2">total sleep</span
              >
            </p>
          </div>
        </div>
      </Card>
    {/if}

    {#if !n.missing}
      <!-- Sleep metrics row -->
      <div class="grid grid-cols-3 gap-2">
        <Card style="padding: 8px 10px;">
          <MetricBadge label="HRV" value={n.hrv} unit="ms" color="var(--teal)" sub="Avg" />
        </Card>
        <Card style="padding: 8px 10px;">
          <MetricBadge label="RHR" value={n.hr} unit="bpm" color="var(--blue)" sub="Avg" />
        </Card>
        <Card style="padding: 8px 10px;">
          <MetricBadge label="Debt" value={n.debt} unit="m" color="var(--amber)" sub="Debt" />
        </Card>
      </div>

      <!-- 28-Day Trend -->
      <Card>
        <div class="flex justify-between items-center mb-3">
          <p class="text-[13px] font-semibold">28-Day Sleep Trend</p>
          <span class="text-[10px] text-text2 font-mono">{n.score}% current</span>
        </div>
        {#if (athleteStore.biometrics?.sleepScores?.length || 0) > 1}
          <div class="h-[60px]">
            <LineChart
              data={athleteStore.biometrics.sleepScores}
              color={getSleepColor(n.score)}
              height={60}
              formatValue={(v) => `${v}%`}
              getValueColor={getSleepColor}
            />
          </div>
        {:else if (athleteStore.biometrics?.sleepData?.length || 0) > 1}
           <!-- Fallback to duration if scores missing -->
           <div class="h-[60px]">
            <LineChart
              data={athleteStore.biometrics.sleepData}
              color={getSleepColor(n.score)}
              height={60}
              formatValue={(v) => `${v.toFixed(1)}h`}
            />
          </div>
        {:else}
          <div class="h-[60px] flex items-center justify-center text-[10px] text-text2 italic">Pending trend data...</div>
        {/if}
      </Card>

      <!-- Stage breakdown -->
      <Card>
        <p class="text-[13px] font-semibold mb-3">Sleep Stages</p>
        <!-- Stacked bar -->
        <div class="flex h-5 rounded-md overflow-hidden gap-0.5 mb-3.5">
          {#each [["deep", n.deep], ["rem", n.rem], ["light", n.light], ["awake", n.awake]] as [k, v] (k)}
            <div
              style="flex: {v}; background: {stageColors[k as string]}"
            ></div>
          {/each}
        </div>
        <div class="flex flex-col gap-2">
          {#each [{ key: "deep", label: "Deep Sleep", pct: n.deep, mins: Math.round((n.durationRaw * n.deep) / 100), ideal: "15–25%", desc: "Physical restoration, immune function, memory consolidation" }, { key: "rem", label: "REM Sleep", pct: n.rem, mins: Math.round((n.durationRaw * n.rem) / 100), ideal: "20–25%", desc: "Cognitive restoration, emotional processing, learning" }, { key: "light", label: "Light Sleep", pct: n.light, mins: Math.round((n.durationRaw * n.light) / 100), ideal: "45–55%", desc: "Transition stage, memory consolidation support" }, { key: "awake", label: "Awake", pct: n.awake, mins: Math.round((n.durationRaw * n.awake) / 100), ideal: "< 10%", desc: "Brief wakings during night; normal up to 10%" }] as s (s.key)}
            <div
              class="flex gap-2.5 py-2 {s.key !== 'awake'
                ? 'border-b border-border'
                : ''}"
            >
              <div
                class="w-2.5 h-2.5 rounded-sm mt-0.5 shrink-0"
                style="background: {stageColors[s.key]}"
              ></div>
              <div class="flex-1">
                <div class="flex justify-between mb-0.5">
                  <span class="text-[12px] font-semibold">{s.label}</span>
                  <div class="flex gap-2.5 items-center">
                    <span class="text-[10px] text-text2 font-mono"
                      >goal {s.ideal}</span
                    >
                    <span
                      class="text-[12px] font-bold font-mono"
                      style="color: {stageColors[s.key]}"
                    >
                      {s.pct}%
                      <span class="text-[9px] font-normal text-text2"
                        >{s.mins}m</span
                      >
                    </span>
                  </div>
                </div>
                <p class="text-[10px] text-text2 leading-tight">{s.desc}</p>
              </div>
            </div>
          {/each}
        </div>
      </Card>
      
      <!-- Individual Sleep Sessions (Naps) -->
      {#if n.periods && n.periods.length > 0}
        <Card>
          <p class="text-[13px] font-semibold mb-3">Sleep Sessions</p>
          <div class="flex flex-col gap-2">
            {#each n.periods as period}
              <div class="flex items-center justify-between p-2.5 rounded-lg bg-glass border border-border/50">
                <div class="flex flex-col gap-0.5">
                  <div class="flex items-center gap-1.5">
                    <span class="text-[12px] font-bold">{period.label}</span>
                    {#if period.score}
                      <Tag color={getSleepColor(period.score)}>{period.score}%</Tag>
                    {/if}
                  </div>
                  <span class="text-[10px] text-text2 font-mono uppercase tracking-wider">{period.timeRange}</span>
                </div>
                <div class="text-right">
                  <span class="text-[13px] font-bold block">{period.duration}</span>
                  <span class="text-[9px] text-text2 uppercase tracking-widest font-medium">Asleep</span>
                </div>
              </div>
            {/each}
          </div>
        </Card>
      {/if}

      <!-- Contextual Insight -->
      <Card
        style="background: linear-gradient(135deg, rgba(70,33,255,0.12), transparent);"
      >
        <p class="text-[13px] font-semibold mb-1.5">Sleep Analysis</p>
        <p class="text-xs text-text1 leading-relaxed">
          {#if n.deep < 15}
            Your deep sleep is below your baseline. Focus on reducing screen
            time and cooling your room tonight.
          {:else if n.rem < 20}
            REM sleep is slightly low. This might affect cognitive performance
            today.
          {:else}
            Your sleep architecture looks balanced. Recovery is on track.
          {/if}
        </p>
      </Card>
    {/if}
  {/if}
</div>
