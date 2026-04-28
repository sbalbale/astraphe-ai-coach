<script lang="ts">
  import Card from "$lib/components/Card.svelte";
  import MetricBadge from "$lib/components/MetricBadge.svelte";
  import Tag from "$lib/components/Tag.svelte";
  import Pill from "$lib/components/Pill.svelte";
  import RadialProgress from "$lib/components/RadialProgress.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import { athleteStore } from "$lib/stores/athleteStore.svelte";
  import { format, parseISO } from "date-fns";
  import { calculateSleepScore } from "$lib/utils/biometrics";

  const isConnected = $derived(
    Object.values(athleteStore.syncStatus?.integrations || {}).some(
      (i: any) => i.connected,
    ),
  );
  const hasData = $derived(athleteStore.biometrics?.series?.length > 0);

  let nightIndex = $state(0);
  let initialSelectDone = $state(false);

  $effect(() => {
    // Default to the first night that actually has data, but only on initial load
    if (
      hasData &&
      !athleteStore.loading &&
      !initialSelectDone &&
      nights.length > 0
    ) {
      const firstData = nights.findIndex((nt) => !nt.missing);
      if (firstData !== -1) {
        nightIndex = firstData;
        initialSelectDone = true;
      }
    }
  });

  // Map biometrics to nights array (filling in missing dates for the last 7 days)
  let nights = $derived.by(() => {
    // Generate last 7 dates ending with Today
    const dates = Array.from({ length: 7 }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - i);
      return format(d, "yyyy-MM-dd");
    });

    return dates.map((displayDateStr) => {
      // displayDateStr is the day you wake up (e.g. April 27)
      // dataDateStr is the day the sleep started in the DB (e.g. April 26)
      const d = new Date(displayDateStr + "T12:00:00"); // Use noon to avoid TZ issues during subtraction
      d.setDate(d.getDate() - 1);
      const dataDateStr = format(d, "yyyy-MM-dd");

      const b = athleteStore.biometrics?.series?.find(
        (s: any) => s.date === dataDateStr,
      );

      const isToday = displayDateStr === format(new Date(), "yyyy-MM-dd");
      const dateLabel = isToday
        ? "Today"
        : format(parseISO(displayDateStr), "MMM d");

      if (!b || (!b.sleep_score && !b.sleep_duration_min)) {
        return {
          date: dateLabel,
          label: format(parseISO(displayDateStr), "MMM d"),
          missing: true,
          score: 0,
        };
      }

      const h = Math.floor((b.sleep_duration_min || 0) / 60);
      const m = Math.round((b.sleep_duration_min || 0) % 60);

      return {
        date: dateLabel,
        label: format(parseISO(displayDateStr), "MMM d"),
        score: b.astrape_sleep_score || b.sleep_score || 0,
        duration: b.sleep_duration_min ? `${h}h ${m}m` : "0h 0m",
        durationRaw: b.sleep_duration_min || 0,
        quality:
          (b.sleep_score || 0) >= 85
            ? "Excellent"
            : (b.sleep_score || 0) >= 70
              ? "Good"
              : "Fair",
        bedtime: b.sleep_bedtime
          ? new Date(b.sleep_bedtime).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })
          : "N/A",
        wakeup: b.sleep_wakeup
          ? new Date(b.sleep_wakeup).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
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
        missing: false,
      };
    });
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
      ? n.score >= 85
        ? "#00C8A8"
        : n.score >= 70
          ? "#FFCB88"
          : "#F07178"
      : "#text2",
  );
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
    <!-- Night selector -->
    <div class="flex gap-1.5 overflow-x-auto pb-0.5 shrink-0">
      {#each nights as nt, i}
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
                >{n.score >= 85
                  ? "OPTIMAL"
                  : n.score >= 70
                    ? "GOOD"
                    : "FAIR"}</Tag
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

      <!-- Stage breakdown -->
      <Card>
        <p class="text-[13px] font-semibold mb-3">Sleep Stages</p>
        <!-- Stacked bar -->
        <div class="flex h-5 rounded-md overflow-hidden gap-0.5 mb-3.5">
          {#each [["deep", n.deep], ["rem", n.rem], ["light", n.light], ["awake", n.awake]] as [k, v]}
            <div
              style="flex: {v}; background: {stageColors[k as string]}"
            ></div>
          {/each}
        </div>
        <div class="flex flex-col gap-2">
          {#each [{ key: "deep", label: "Deep Sleep", pct: n.deep, mins: Math.round((n.durationRaw * n.deep) / 100), ideal: "15–25%", desc: "Physical restoration, immune function, memory consolidation" }, { key: "rem", label: "REM Sleep", pct: n.rem, mins: Math.round((n.durationRaw * n.rem) / 100), ideal: "20–25%", desc: "Cognitive restoration, emotional processing, learning" }, { key: "light", label: "Light Sleep", pct: n.light, mins: Math.round((n.durationRaw * n.light) / 100), ideal: "45–55%", desc: "Transition stage, memory consolidation support" }, { key: "awake", label: "Awake", pct: n.awake, mins: Math.round((n.durationRaw * n.awake) / 100), ideal: "< 10%", desc: "Brief wakings during night; normal up to 10%" }] as s}
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
