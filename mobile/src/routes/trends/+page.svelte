<script lang="ts">
  import { onMount } from 'svelte';
  import { addDays, format, startOfWeek, subDays } from 'date-fns';
  import { api } from '$lib/api';
  import type { Workout } from '$lib/types/training';
  import { weeklyTssTarget } from '$lib/utils/weeklyTarget';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { formCssColor } from '$lib/scoreColors';

  let planned = $state<Workout[]>([]);
  const weeksStart = () => startOfWeek(subDays(new Date(), 11 * 7), { weekStartsOn: 1 });

  onMount(async () => {
    athleteStore.fetchAll();
    const start = format(weeksStart(), 'yyyy-MM-dd');
    const end = format(addDays(startOfWeek(new Date(), { weekStartsOn: 1 }), 6), 'yyyy-MM-dd');
    planned = await api.getWorkouts(start, end);
  });

  $effect(() => {
    pageHeader.eyebrow = 'Last 12 weeks';
    return resetPageHeader;
  });

  type LoadRow = { date: string; day: string; ctl: number; atl: number; tsb?: number; daily_tss?: number };

  const rows = $derived.by<LoadRow[]>(() =>
    [...(athleteStore.metrics?.trainingLoadData ?? [])]
      .filter((r: any) => r?.date)
      .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
  );
  const windowRows = $derived(rows.filter((r) => r.date >= format(subDays(new Date(), 83), 'yyyy-MM-dd')));
  const latest = $derived(rows.length ? rows[rows.length - 1] : null);
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);

  /** Fitness change over the last 28 days. */
  const fitnessDelta = $derived.by(() => {
    if (!latest || rows.length < 29) return null;
    const then = rows[rows.length - 29];
    return Math.round((latest.ctl - then.ctl) * 10) / 10;
  });

  /** Weekly actual and planned TSS for the last 12 Monday-start weeks, oldest first. */
  const weeks = $derived.by(() => {
    const start = weeksStart();
    const buckets = Array.from({ length: 12 }, (_, i) => ({
      start: new Date(start.getFullYear(), start.getMonth(), start.getDate() + i * 7),
      tss: 0,
      planned: 0
    }));
    const indexOf = (d: Date) => Math.floor((d.getTime() - buckets[0].start.getTime()) / (7 * 24 * 3600 * 1000));
    for (const r of rows) {
      const idx = indexOf(new Date(r.date + "T00:00:00"));
      if (idx >= 0 && idx < 12) buckets[idx].tss += Number(r.daily_tss) || 0;
    }
    for (const p of planned) {
      const idx = indexOf(new Date(p.date + "T00:00:00"));
      if (idx >= 0 && idx < 12) buckets[idx].planned += Number(p.projected_tss) || 0;
    }
    return buckets.map((b) => ({ ...b, tss: Math.round(b.tss), planned: Math.round(b.planned) }));
  });
  const maxTss = $derived(Math.max(1, ...weeks.map((w) => Math.max(w.tss, w.planned))));
  const avgTss = $derived(Math.round(weeks.reduce((a, w) => a + w.tss, 0) / Math.max(1, weeks.filter((w) => w.tss > 0).length)));
  const target = $derived(weeklyTssTarget(athleteStore.ctl, Number((athleteStore.profile as any)?.weekly_tss_target) || null));
  let pickedWeek = $state<number | null>(null);
  const activeWeek = $derived(pickedWeek ?? weeks.length - 1);
  const activeInfo = $derived.by(() => {
    const w = weeks[activeWeek];
    if (!w) return null;
    const end = addDays(w.start, 6);
    return { ...w, range: `${format(w.start, "d MMM")} – ${format(end, "d MMM")}`, weekNo: format(w.start, "I"), current: activeWeek === weeks.length - 1 };
  });
  const fmt1 = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? '--' : n.toFixed(1));

  // --- Training-load chart (design: smooth fitness line + area, dashed fatigue, end dot) ---
  const CHART_W = 318;
  const CHART_H = 124;
  let scrubIndex = $state<number | null>(null);
  const chart = $derived.by(() => {
    const n = windowRows.length;
    if (n < 2) return null;
    const vals = windowRows.flatMap((p) => [Number(p.ctl) || 0, Number(p.atl) || 0]);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const span = Math.max(hi - lo, 1);
    const x = (i: number) => (i / (n - 1)) * CHART_W;
    const y = (v: number) => 10 + (1 - (v - lo) / span) * 100;
    const sampled = windowRows.map((_, i) => i).filter((i) => i % 3 === 0 || i === n - 1);
    const fit = sampled.map((i) => ({ x: x(i), y: y(Number(windowRows[i].ctl) || 0) }));
    const fat = sampled.map((i) => `${x(i).toFixed(1)},${y(Number(windowRows[i].atl) || 0).toFixed(1)}`).join(" ");
    // Catmull-Rom -> cubic Bezier so the fitness line reads as one smooth curve.
    let d = `M${fit[0].x.toFixed(1)},${fit[0].y.toFixed(1)}`;
    for (let i = 0; i < fit.length - 1; i++) {
      const p0 = fit[Math.max(0, i - 1)], p1 = fit[i], p2 = fit[i + 1], p3 = fit[Math.min(fit.length - 1, i + 2)];
      const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
    }
    return { line: d, area: `${d} L${CHART_W},${CHART_H} L0,${CHART_H} Z`, fatigue: fat, x, y, n };
  });
  /** The day under the finger (or the latest day when idle). */
  const shown = $derived.by(() => {
    const i = scrubIndex ?? windowRows.length - 1;
    const row = windowRows[i];
    if (!row) return null;
    const ctl = Number(row.ctl) || 0;
    const atl = Number(row.atl) || 0;
    const tsb = row.tsb != null && Number.isFinite(Number(row.tsb)) ? Number(row.tsb) : ctl - atl;
    const d = new Date(row.date + "T00:00:00");
    return { i, ctl, atl, tsb, label: `${format(d, "EEE d MMM")} · Wk ${format(d, "I")}` };
  });
  function scrubTo(ev: PointerEvent) {
    if (!chart) return;
    const el = ev.currentTarget as SVGSVGElement;
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (ev.clientX - rect.left) / Math.max(rect.width, 1)));
    scrubIndex = Math.round(ratio * (chart.n - 1));
  }
</script>

<div class="flex flex-col gap-3.5">
  {#if athleteStore.initialLoadDone && rows.length === 0}
    <EmptyState title="No trend data yet" message="Your fitness and fatigue trends appear once a few weeks of workouts have synced." icon="📈" />
  {:else}
    <dl class="m-0 grid grid-cols-4 gap-2">
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fitness</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{fmt1(latest?.ctl)}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fatigue</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{fmt1(latest?.atl)}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Form</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]" style="color: {latest?.tsb == null ? 'var(--text0)' : formCssColor(latest.tsb)}">{latest?.tsb == null ? '--' : `${latest.tsb > 0 ? '+' : ''}${latest.tsb.toFixed(1)}`}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">FTP</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{ftp || '--'}{#if ftp}<span class="text-[11px] text-text2 font-normal"> W</span>{/if}</dd></div>
    </dl>

    <section aria-label="Training load" class="bg-bg2 border border-border rounded-[24px] px-[18px] pt-[18px] pb-3.5 flex flex-col gap-2.5">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">Training load</h2>
        {#if fitnessDelta !== null}
          <span class="text-xs" style="color: {fitnessDelta >= 0 ? 'var(--green)' : 'var(--amber)'}">{fitnessDelta >= 0 ? '+' : ''}{fitnessDelta} in 4 wks</span>
        {/if}
      </div>
      {#if shown}
        <div class="flex items-baseline justify-between gap-2" aria-live="polite">
          <span class="font-mono text-[11px] text-text2 uppercase">{scrubIndex === null ? "Latest" : shown.label}</span>
          <span class="flex gap-3 text-xs font-mono tabular-nums">
            <span><span class="text-text2">Fit </span><span style="color: var(--blue)">{shown.ctl.toFixed(1)}</span></span>
            <span><span class="text-text2">Fat </span>{shown.atl.toFixed(1)}</span>
            <span><span class="text-text2">Form </span><span style="color: {formCssColor(shown.tsb)}">{shown.tsb > 0 ? "+" : ""}{shown.tsb.toFixed(1)}</span></span>
          </span>
        </div>
      {/if}
      {#if chart}
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <svg
          viewBox="0 0 {CHART_W} {CHART_H}"
          width="100%"
          role="img"
          aria-label="Fitness trend with fatigue overlaid over the last 12 weeks. Drag to read values."
          class="block touch-none select-none cursor-crosshair"
          onpointerdown={(e) => { (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId); scrubTo(e); }}
          onpointermove={scrubTo}
          onpointerup={() => (scrubIndex = null)}
          onpointercancel={() => (scrubIndex = null)}
          onpointerleave={(e) => { if (e.pointerType === "mouse") scrubIndex = null; }}
        >
          {#each [28, 62, 96] as gy (gy)}<line x1="0" y1={gy} x2={CHART_W} y2={gy} stroke="var(--bg3)" stroke-width="1"></line>{/each}
          <polyline fill="none" stroke="var(--chartAtl, #6A6A72)" stroke-width="1.4" stroke-dasharray="3 3" points={chart.fatigue}></polyline>
          <path d={chart.area} fill="var(--blue)" fill-opacity="0.10"></path>
          <path d={chart.line} fill="none" stroke="var(--blue)" stroke-width="2"></path>
          {#if shown}
            {@const cx = chart.x(shown.i)}
            {#if scrubIndex !== null}<line x1={cx} y1="0" x2={cx} y2={CHART_H} stroke="var(--text2)" stroke-width="1" stroke-opacity="0.6"></line>{/if}
            <circle cx={cx} cy={chart.y(shown.ctl)} r="3.5" fill="var(--blue)"></circle>
            {#if scrubIndex !== null}<circle cx={cx} cy={chart.y(shown.atl)} r="3" fill="var(--bg2)" stroke="var(--text1)" stroke-width="1.5"></circle>{/if}
          {/if}
        </svg>
      {/if}
      <div class="flex gap-4 text-[11px] text-text2">
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 bg-chartCtl"></span>Fitness (42d)</span>
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 border-t-2 border-dashed border-chartAtl"></span>Fatigue (7d)</span>
        {#if windowRows.length > 1}
          <span class="ml-auto font-mono uppercase">{format(new Date(windowRows[0].date + 'T00:00:00'), 'MMM')} → {format(new Date(windowRows[windowRows.length - 1].date + 'T00:00:00'), 'MMM')}</span>
        {/if}
      </div>
    </section>

    <section aria-label="Weekly TSS" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-3">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">Weekly TSS</h2>
        <span class="font-mono text-[11px] text-text2">AVG {avgTss}{#if target} · TARGET {target}{/if}</span>
      </div>
      {#if activeInfo}
        <div class="flex items-baseline justify-between gap-2" aria-live="polite">
          <span class="font-mono text-[11px] text-text2 uppercase">{activeInfo.current ? "This week" : `Wk ${activeInfo.weekNo}`} · {activeInfo.range}</span>
          <span class="flex gap-3 text-xs font-mono tabular-nums">
            <span><span class="text-text2">TSS </span><span style="color: var(--blue)">{activeInfo.tss}</span></span>
            <span><span class="text-text2">Plan </span>{activeInfo.planned > 0 ? activeInfo.planned : "—"}</span>
          </span>
        </div>
      {/if}
      <div role="group" aria-label="Weekly TSS over the last 12 weeks. Tap a bar for details." class="flex items-end gap-1.5 h-[72px]">
        {#each weeks as w, i (i)}
          <button
            type="button"
            aria-label="Week of {format(w.start, 'd MMM')}: {w.tss} TSS, planned {w.planned}"
            aria-pressed={i === activeWeek}
            class="relative flex-1 h-full p-0 border-0 bg-transparent cursor-pointer"
            onclick={() => (pickedWeek = pickedWeek === i ? null : i)}
            onpointerenter={(e) => { if (e.pointerType === "mouse") pickedWeek = i; }}
            onpointerleave={(e) => { if (e.pointerType === "mouse") pickedWeek = null; }}
          >
            {#if w.planned > 0}
              <span aria-hidden="true" class="absolute bottom-0 left-0 right-0 rounded border border-dashed border-text2" style="height: {Math.max(3, Math.round((w.planned / maxTss) * 72))}px"></span>
            {/if}
            <span aria-hidden="true" class="absolute bottom-0 left-0 right-0 rounded" style="height: {Math.max(2, Math.round((w.tss / maxTss) * 72))}px; background: {i === activeWeek ? 'var(--blue)' : i === weeks.length - 1 ? 'var(--blue)' : 'var(--bg3)'}; opacity: {i === activeWeek || i === weeks.length - 1 ? 1 : 0.9}"></span>
          </button>
        {/each}
      </div>
      <div class="flex justify-between items-center font-mono text-[10px] text-text2">
        <span>W{format(weeks[0].start, "I")}</span><span>W{format(weeks[5].start, "I")}</span><span>THIS WK</span>
      </div>
      <div class="flex gap-4 text-[11px] text-text2">
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3 h-2 rounded-sm bg-bg3"></span>Actual</span>
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3 h-2 rounded-sm border border-dashed border-text2"></span>Planned</span>
      </div>
    </section>
  {/if}
</div>
