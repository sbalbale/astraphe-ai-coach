<script lang="ts">
  import { localDay } from '$lib/utils/localDay';
  import { onMount } from 'svelte';
  import { format, subDays } from 'date-fns';
  import { api } from '$lib/api';
  import { navTo } from '$lib/nav';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { currentRecoveryState, firstPositiveFiniteNumber, readinessScoreFromRow } from '$lib/utils/biometrics';
  import {
    BAND_COPY,
    FORM_WEIGHT,
    RECOVERY_WEIGHT,
    baseline,
    readinessBand,
    readinessBreakdown,
    sparkline,
    type ReadinessBand
  } from '$lib/readiness';
  import type { Workout } from '$lib/types/training';

  let todaySessions = $state<Workout[]>([]);
  onMount(async () => {
    athleteStore.fetchAll();
    const iso = format(new Date(), 'yyyy-MM-dd');
    todaySessions = await api.getWorkouts(iso, iso);
  });

  const now = new Date();
  const todayIso = format(now, 'yyyy-MM-dd');

  type Row = Record<string, any> & { date?: string };
  const series = $derived<Row[]>(athleteStore.biometrics?.series ?? []);
  const byDate = $derived(new Map(series.filter((r) => r?.date).map((r) => [r.date as string, r])));
  const loadByDate = $derived(
    new Map(((athleteStore.metrics?.trainingLoadData ?? []) as Row[]).filter((r) => r?.date).map((r) => [String(r.date).slice(0, 10), r]))
  );

  const current = $derived(currentRecoveryState(series, athleteStore.profile?.timezone_offset_min));
  const row = $derived(current.row as Row | null);
  const score = $derived(readinessScoreFromRow(row));
  const recovery = $derived(firstPositiveFiniteNumber(row?.recovery_score));
  /** Form as the backend uses it for readiness: that day's fitness minus the previous day's fatigue. */
  function formFor(dateIso: string): number | null {
    const ctl = Number(loadByDate.get(dateIso)?.ctl);
    const atl = Number(loadByDate.get(format(subDays(new Date(dateIso + 'T12:00:00'), 1), 'yyyy-MM-dd'))?.atl);
    return Number.isFinite(ctl) && Number.isFinite(atl) ? ctl - atl : null;
  }
  const scoreDate = $derived(row?.date ?? todayIso);
  // The store's current form only stands in for *today's* score, never an older day's.
  // Before the store has loaded, its tsb is a placeholder 0, not a real form value.
  const tsb = $derived(
    formFor(scoreDate) ??
      (scoreDate === todayIso && athleteStore.initialLoadDone ? Number(athleteStore.tsb) : NaN)
  );
  const breakdown = $derived(readinessBreakdown(recovery, tsb));
  const band = $derived<ReadinessBand>(readinessBand(score ?? breakdown.total));

  // The day before the score's own day: when today's row hasn't synced and yesterday's
  // score is shown, comparing with "yesterday" compared the row with itself (±0).
  const yesterday = $derived(
    readinessScoreFromRow(byDate.get(format(subDays(new Date(scoreDate + 'T12:00:00'), 1), 'yyyy-MM-dd')))
  );
  const delta = $derived(score != null && yesterday != null ? score - yesterday : null);

  const SUMMARY: Record<ReadinessBand, string> = {
    high: "You're well recovered and carrying freshness. A good day for quality work if it's on the plan.",
    mid: "You're mostly recovered. Good enough for today's planned session — not a day to add extra.",
    low: 'Recovery is low today. Keep it easy or take the rest; pushing now costs more than it gains.'
  };

  // --- drivers: last 14 days vs 30-day baseline ---
  const last14 = $derived(Array.from({ length: 14 }, (_, i) => format(subDays(now, 13 - i), 'yyyy-MM-dd')));
  const last30 = $derived(Array.from({ length: 30 }, (_, i) => format(subDays(now, 30 - i), 'yyyy-MM-dd')));
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null);
  const hm = (mins: number) => `${Math.floor(mins / 60)}h ${String(Math.round(mins % 60)).padStart(2, '0')}m`;

  type Driver = { name: string; value: string; delta: string; arrow: string; good: boolean | null; stroke: string; spark: ReturnType<typeof sparkline> };
  function driver(
    name: string,
    pick: (d: string) => number | null,
    opts: { fmt: (v: number) => string; pct?: boolean; higherIsBetter: boolean; accent?: boolean; currentValue?: number | null; valueLabel?: string }
  ): Driver | null {
    const values = last14.map(pick);
    const base = baseline(last30.map(pick));
    const cur = opts.currentValue ?? [...values].reverse().find((v) => v != null) ?? null;
    if (cur == null) return null;
    let deltaText = '';
    let good: boolean | null = null;
    let arrow = '';
    if (base && base.mean) {
      const raw = cur - base.mean;
      const shown = opts.pct ? (raw / base.mean) * 100 : raw;
      const r = Math.round(shown * 10) / 10;
      deltaText = `${r > 0 ? '+' : r < 0 ? '−' : ''}${opts.pct ? Math.round(Math.abs(r)) + '%' : Math.abs(r) % 1 ? Math.abs(r).toFixed(1) : String(Math.abs(r))}`;
      arrow = r > 0 ? '↑' : r < 0 ? '↓' : '';
      good = r === 0 ? null : (r > 0) === opts.higherIsBetter;
    }
    return {
      name,
      value: opts.valueLabel ?? opts.fmt(cur),
      delta: deltaText,
      arrow,
      good,
      stroke: opts.accent ? 'var(--blue)' : 'var(--text1)',
      spark: sparkline(values, base)
    };
  }

  const drivers = $derived(
    [
      driver('HRV', (d) => num(byDate.get(d)?.hrv_rmssd), { fmt: (v) => `${Math.round(v)} ms`, pct: true, higherIsBetter: true, accent: true, currentValue: num(row?.hrv_rmssd) }),
      driver('Resting HR', (d) => num(byDate.get(d)?.resting_hr), { fmt: (v) => `${Math.round(v)} bpm`, higherIsBetter: false, currentValue: num(row?.resting_hr) }),
      driver('Sleep', (d) => num(byDate.get(d)?.sleep_duration_min), {
        fmt: (v) => hm(v),
        pct: true,
        higherIsBetter: true,
        currentValue: num(row?.sleep_duration_min),
        valueLabel: num(row?.sleep_duration_min) ? `${hm(row!.sleep_duration_min)}${num(row?.sleep_score) ? ` · ${row!.sleep_score}` : ''}` : undefined
      }),
      driver('Fitness', (d) => num(loadByDate.get(d)?.ctl), { fmt: (v) => v.toFixed(1), higherIsBetter: true }),
      driver('Fatigue', (d) => num(loadByDate.get(d)?.atl), { fmt: (v) => v.toFixed(1), higherIsBetter: false })
    ].filter((d): d is Driver => d !== null)
  );

  // --- 14-day readiness bars ---
  const trend = $derived(
    last14.map((d) => {
      const r = byDate.get(d);
      return {
        date: d,
        score: readinessScoreFromRow(r),
        recovery: firstPositiveFiniteNumber(r?.recovery_score),
        form: formFor(d),
        workouts: (athleteStore.workouts ?? [])
          .filter((w: any) => localDay(w?.started_at) === d)
          .map((w: any) => w?.title || w?.sport || 'Workout') as string[]
      };
    })
  );
  let pickedDay = $state<number | null>(null);
  const shownDay = $derived(trend[pickedDay ?? trend.length - 1]);
  const trendScores = $derived(trend.map((t) => t.score).filter((s): s is number => s != null));
  const trendAvg = $derived(trendScores.length ? Math.round(trendScores.reduce((a, b) => a + b, 0) / trendScores.length) : null);
  const bandColor = (s: number) => (s >= 67 ? 'var(--teal)' : s >= 34 ? 'var(--amber)' : 'var(--red)');

  const session = $derived(todaySessions[0] ?? null);
</script>

<div class="flex flex-col gap-4 pt-1 pb-6">
  <button type="button" class="self-start h-11 flex items-center gap-1 border-0 bg-transparent p-0 text-sm text-text1 cursor-pointer" onclick={() => navTo('/dashboard')}>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>Today
  </button>

  {#if score == null}
    <section class="bg-bg2 border border-dashed border-border rounded-[24px] p-6 text-center">
      <p class="m-0 text-[15px] font-semibold mb-1">No readiness yet</p>
      <p class="m-0 text-[13px] text-text2">Readiness appears once your watch syncs a night of recovery data.</p>
    </section>
  {:else}
    <!-- Score + verdict -->
    <header class="flex flex-col gap-2.5">
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2 uppercase">{format(now, 'EEE dd MMM')} · Readiness</span>
      <div class="flex items-end gap-4">
        <span class="font-display text-[96px] leading-[0.85]">{score}</span>
        <span class="flex flex-col gap-1 pb-1.5">
          <span class="font-mono text-[11px] tracking-[0.14em] uppercase" style="color: {BAND_COPY[band].color}">{BAND_COPY[band].verdict}</span>
          {#if delta !== null}<span class="text-[13px] text-text2">{delta > 0 ? '+' : delta < 0 ? '−' : '±'}{Math.abs(delta)} {scoreDate === todayIso ? 'vs yesterday' : 'vs the day before'}</span>{/if}
        </span>
      </div>
      <p class="m-0 text-[15px] leading-normal text-text1">{SUMMARY[band]}</p>
    </header>

    <!-- How it's built -->
    <section aria-label="How it's built" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-3.5">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">How it's built</h2>
        <span class="font-mono text-[11px] text-text2">{breakdown.recovery != null ? `${RECOVERY_WEIGHT * 100} / ${FORM_WEIGHT * 100}` : 'FORM ONLY'}</span>
      </div>
      <div role="img" aria-label="Readiness made of recovery {breakdown.recoveryPart?.toFixed(1) ?? 0} and form {breakdown.formPart.toFixed(1)} points" class="flex h-3 rounded-md overflow-hidden bg-bg3">
        {#if breakdown.recoveryPart != null}<span class="bg-blue" style="width: {breakdown.recoveryPart}%"></span>{/if}
        <span class="bg-text2 border-l-2 border-bg2" style="width: {breakdown.formPart}%"></span>
      </div>
      <div class="flex flex-col">
        {#if breakdown.recovery != null}
          <div class="grid grid-cols-[10px_1fr_auto] gap-2.5 items-center py-2.5 border-t border-border">
            <span aria-hidden="true" class="w-2.5 h-2.5 rounded-[3px] bg-blue"></span>
            <span class="flex flex-col gap-0.5"><span class="text-sm font-medium">Recovery · {Math.round(breakdown.recovery)}%</span><span class="text-xs text-text2">How your body bounced back overnight · weighted {RECOVERY_WEIGHT * 100}%</span></span>
            <span class="font-mono text-sm">{breakdown.recoveryPart?.toFixed(1)}</span>
          </div>
        {/if}
        <div class="grid grid-cols-[10px_1fr_auto] gap-2.5 items-center py-2.5 border-t border-border">
          <span aria-hidden="true" class="w-2.5 h-2.5 rounded-[3px] bg-text2"></span>
          <span class="flex flex-col gap-0.5"><span class="text-sm font-medium">Form · {Number.isFinite(tsb) ? `${tsb > 0 ? '+' : ''}${tsb.toFixed(1)}` : '--'} → {Number.isFinite(tsb) ? Math.round(breakdown.formScore) : '--'}</span><span class="text-xs text-text2">Fitness minus fatigue, scaled 0–100{breakdown.recovery != null ? ` · weighted ${FORM_WEIGHT * 100}%` : ''}</span></span>
          <span class="font-mono text-sm">{breakdown.formPart.toFixed(1)}</span>
        </div>
        <div class="flex justify-between pt-2.5 border-t border-border text-[13px]">
          <span class="text-text2">Readiness (rounded)</span>
          <span class="font-mono font-medium">{score}</span>
        </div>
      </div>
    </section>

    <!-- What's driving it -->
    {#if drivers.length}
      <section aria-label="What's driving it" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col">
        <div class="flex justify-between items-baseline pb-2">
          <h2 class="m-0 font-display font-normal text-2xl">What's driving it</h2>
          <span class="font-mono text-[11px] text-text2">VS 30-DAY BASELINE</span>
        </div>
        {#each drivers as d (d.name)}
          <div class="grid grid-cols-[1fr_96px_64px] gap-2.5 items-center py-2.5 border-t border-border">
            <span class="flex flex-col gap-0.5 min-w-0">
              <span class="text-xs text-text2">{d.name}</span>
              <span class="text-base font-medium truncate">{d.value}</span>
            </span>
            <svg width="96" height="32" viewBox="0 0 96 32" aria-hidden="true" class="block">
              {#if d.spark}
                {#if d.spark.bandH}<rect x="0" y={d.spark.bandY} width="96" height={d.spark.bandH} rx="3" fill="var(--text0)" fill-opacity="0.04"></rect>{/if}
                <polyline fill="none" stroke={d.stroke} stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" points={d.spark.points}></polyline>
              {/if}
            </svg>
            <span class="flex items-center justify-end gap-1 text-xs" style="color: {d.good === null ? 'var(--text2)' : d.good ? 'var(--green)' : 'var(--amber)'}">
              {#if d.arrow}<span aria-hidden="true">{d.arrow}</span>{/if}{d.delta}
            </span>
          </div>
        {/each}
      </section>
    {/if}

    <!-- Last 14 days -->
    <section aria-label="Last 14 days of readiness" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-3">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">Last 14 days</h2>
        {#if trendAvg != null}<span class="font-mono text-[11px] text-text2">AVG {trendAvg}</span>{/if}
      </div>
      {#if shownDay}
        <div class="flex items-baseline justify-between gap-3" aria-live="polite">
          <span class="font-mono text-[11px] text-text2 uppercase">{shownDay.date === todayIso ? 'Today' : format(new Date(shownDay.date + 'T12:00:00'), 'EEE d MMM')}</span>
          <span class="flex gap-3 font-mono text-xs tabular-nums">
            <span><span class="text-text2">Ready </span><span style="color: {shownDay.score != null ? bandColor(shownDay.score) : 'var(--text2)'}">{shownDay.score ?? '--'}</span></span>
            <span><span class="text-text2">Rec </span>{shownDay.recovery != null ? `${Math.round(shownDay.recovery)}%` : '--'}</span>
            <span><span class="text-text2">Form </span>{shownDay.form != null ? `${shownDay.form > 0 ? '+' : ''}${shownDay.form.toFixed(1)}` : '--'}</span>
          </span>
        </div>
      {/if}
      <div role="group" aria-label="Readiness over the last 14 days. Tap a day for details." class="flex items-end gap-[5px] h-[84px]">
        {#each trend as t, i (t.date)}
          <button
            type="button"
            aria-label="{format(new Date(t.date + 'T12:00:00'), 'EEEE d MMMM')}: readiness {t.score ?? 'no data'}"
            aria-pressed={i === (pickedDay ?? trend.length - 1)}
            class="flex-1 h-full p-0 border-0 bg-transparent flex items-end cursor-pointer"
            onclick={() => (pickedDay = pickedDay === i ? null : i)}
            onpointerenter={(e) => { if (e.pointerType === 'mouse') pickedDay = i; }}
            onpointerleave={(e) => { if (e.pointerType === 'mouse') pickedDay = null; }}
          >
            <span
              class="block w-full rounded-[5px]"
              style="height: {t.score != null ? Math.max(4, Math.round((t.score / 100) * 84)) : 4}px; background: {t.score != null ? bandColor(t.score) : 'var(--bg3)'}; opacity: {i === (pickedDay ?? trend.length - 1) ? 1 : 0.4}"
            ></span>
          </button>
        {/each}
      </div>
      <div class="flex justify-between font-mono text-[10px] text-text2 uppercase">
        <span>{format(new Date(last14[0] + 'T12:00:00'), 'dd MMM')}</span>
        <span>{format(new Date(last14[7] + 'T12:00:00'), 'dd MMM')}</span>
        <span class="text-text0">Today</span>
      </div>
      {#if shownDay?.workouts.length}
        <p class="m-0 text-xs text-text2 truncate">{shownDay.workouts.join(' · ')}</p>
      {/if}
    </section>

    <!-- What it means today -->
    <section aria-label="What it means today" class="flex flex-col gap-3 p-[18px] rounded-[24px] bg-blue-dim border border-blue/25">
      <span class="font-mono text-[11px] tracking-[0.14em] text-blue">WHAT IT MEANS TODAY</span>
      <p class="m-0 text-[15px] leading-normal text-text0">
        {#if session}
          {#if band === 'low'}
            Swap <strong class="font-semibold">{session.title}</strong> for an easy session or rest.
          {:else if band === 'high'}
            You're ready for <strong class="font-semibold">{session.title}</strong> — push it if it feels good.
          {:else}
            Do <strong class="font-semibold">{session.title}</strong> as written. If the first hard block feels above 7/10, cut it short.
          {/if}
        {:else}
          Nothing planned today. {band === 'low' ? 'Rest or keep any movement very easy.' : band === 'high' ? 'A good day to add quality work if you want it.' : 'An easy aerobic session or a rest day both fit.'}
        {/if}
      </p>
      <div class="grid grid-cols-3 gap-1.5 text-[11px] text-center">
        {#each (['low', 'mid', 'high'] as const) as b (b)}
          <span class="py-2 px-1 rounded-[10px] {band === b ? 'bg-bg0 border border-blue text-text0' : 'bg-bg3 text-text2'}">{BAND_COPY[b].range}<br />{BAND_COPY[b].action}</span>
        {/each}
      </div>
      {#if session}
        <button type="button" class="h-[46px] rounded-[14px] border-0 bg-blue text-[#0B1420] text-sm font-semibold cursor-pointer" onclick={() => navTo('/plan')}>Open today's session</button>
      {/if}
    </section>

    <!-- Data note + explainer -->
    <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-border">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true" class="shrink-0 mt-px text-text2"><circle cx="12" cy="12" r="9"></circle><path d="M12 11v5M12 8h.01"></path></svg>
      <span class="flex flex-col gap-1.5 text-[13px] leading-[1.45] text-text1">
        {#if breakdown.recovery == null}
          <span><span class="text-text0 font-medium">Based on form only.</span> Last night's recovery hasn't synced yet, so this will move once your watch logs sleep.</span>
        {:else}
          <span><span class="text-text0 font-medium">Based on recovery + form.</span> When last night's recovery hasn't synced yet, readiness uses form only and this card says so.</span>
        {/if}
        {#if current.isStale || (current.row && !current.hasTodayRow)}
          <span>Using data from {current.date ? format(new Date(current.date + 'T12:00:00'), 'EEE d MMM') : 'an earlier day'} — sync your device for today's numbers.</span>
        {/if}
        <span><span class="text-text0 font-medium">Readiness vs recovery:</span> recovery is how your body bounced back overnight; readiness is whether today is a day to train hard.</span>
      </span>
    </div>
  {/if}
</div>
