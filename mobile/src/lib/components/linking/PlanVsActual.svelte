<script lang="ts">
  /**
   * Planned vs actual for a linked workout (design: PvA option F, "windows + list").
   * Summary chips, then the planned blocks as target windows over zone bands with the recorded
   * power or heart rate drawn across them (coloured by in / above / below target), then one row
   * per block with its split; tapping a block (chart or row) opens its trace.
   */
  import type { ActivityStreams } from '$lib/services/activityService';
  import type { Interval } from '$lib/types/training';
  import {
    type Fit,
    type Metric,
    type ZoneDefLike,
    hrOnPowerScale,
    inTargetPct,
    mins,
    pct,
    pvaBlocks,
    tracePoints,
    yRange,
    zoneBands
  } from '$lib/utils/planVsActual';

  let {
    structure,
    streams = null,
    ftp = 0,
    zones = [],
    plannedMin,
    plannedTss,
    actualSecs,
    actualTss
  }: {
    structure: Interval[];
    streams?: ActivityStreams | null;
    ftp?: number;
    zones?: ZoneDefLike[];
    plannedMin: number;
    plannedTss: number;
    actualSecs: number;
    actualTss: number | null;
  } = $props();

  const W = 320;
  const PLOT_H = 150;
  const FIT_COLOR: Record<Fit, string> = {
    in: 'var(--green)',
    above: 'var(--amber)',
    below: 'var(--stage-light)',
    none: 'var(--text2)'
  };

  const ts = $derived(streams?.time_series ?? {});
  const step = $derived(streams?.resolution_seconds || 1);
  const hasPower = $derived((ts.watts?.length ?? 0) > 1 && ftp > 0);
  const hasHr = $derived((ts.heartrate?.length ?? 0) > 1);
  const metrics = $derived.by(() => {
    const out: [string, string][] = [];
    if (hasPower) out.push(['power', 'Power']);
    if (hasHr) out.push(['hr', 'Heart rate']);
    if (hasPower && hasHr) out.push(['both', 'Both']);
    return out;
  });
  let picked = $state<'power' | 'hr' | 'both'>('power');
  const view = $derived(metrics.some(([id]) => id === picked) ? picked : ((metrics[0]?.[0] as typeof picked) ?? 'hr'));
  /** The metric the windows and fit use ("Both" judges power and adds HR as a line). */
  const metric = $derived<Metric>(view === 'hr' ? 'hr' : 'power');
  const unit = $derived(metric === 'power' ? 'W' : 'bpm');

  const stream = $derived({ values: metric === 'power' ? ts.watts : ts.heartrate, time: ts.time, step });
  const blocks = $derived(pvaBlocks(structure, stream, metric, ftp, zones));
  const hasStream = $derived(metric === 'power' ? hasPower : hasHr);
  const planned = $derived(blocks.reduce((a, b) => a + b.min, 0) || plannedMin);
  const actualMin = $derived(actualSecs / 60);
  const span = $derived(Math.max(planned, actualMin, 1));
  const [yLo, yHi] = $derived(yRange(metric, ftp, zones));
  const X = (tMin: number) => (Math.min(tMin, span) / span) * W;
  const Y = (v: number) => PLOT_H - ((Math.max(yLo, Math.min(yHi, v)) - yLo) / (yHi - yLo)) * (PLOT_H - 5);

  const bands = $derived(
    zoneBands(metric, ftp, zones)
      .map((z) => ({ ...z, lo: Math.max(z.lo, yLo), hi: Math.min(z.hi, yHi) }))
      .filter((z) => z.hi > z.lo)
  );
  const trace = $derived(hasStream ? tracePoints(stream, blocks) : []);
  // "Both": heart rate drawn in the power chart's zone bands (HR Z2 inside the Z2 band), so the
  // two lines read against the same zones. Without HR zones it falls back to its own bpm scale.
  const hrByZone = $derived(zones.length >= 5);
  const hrTrace = $derived.by(() => {
    if (view !== 'both' || !hasHr) return '';
    const [lo, hi] = yRange('hr', ftp, zones);
    return tracePoints({ values: ts.heartrate, time: ts.time, step }, [])
      .map((p) => {
        const onPower = hrByZone ? hrOnPowerScale(p.v, ftp, zones) : null;
        const y = onPower != null ? Y(onPower) : PLOT_H - ((Math.max(lo, Math.min(hi, p.v)) - lo) / (hi - lo)) * (PLOT_H - 5);
        return `${X(p.tMin).toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  });

  const inPct = $derived(hasStream ? inTargetPct(blocks) : null);
  const summary = $derived(
    [
      inPct != null ? { k: 'In target', v: `${inPct}%`, c: inPct >= 75 ? 'var(--green)' : 'var(--amber)' } : null,
      planned > 0 && actualSecs > 0 ? { k: 'Time', v: `${mins(actualMin)} / ${mins(planned)}`, c: 'var(--text0)' } : null,
      plannedTss > 0 && actualTss != null ? { k: 'TSS', v: `${Math.round(actualTss)} / ${plannedTss}`, c: 'var(--text0)' } : null
    ].filter((x): x is { k: string; v: string; c: string } => x != null)
  );
  const stoppedEarly = $derived(actualMin > 0 && actualMin < planned - 1);

  const zoneVar = (z: number) => (z > 0 ? `var(--zone-${z})` : 'var(--text2)');
  const avgColor = (b: (typeof blocks)[number]) =>
    b.stats.avg == null ? 'var(--text3, var(--text2))' : b.window ? FIT_COLOR[b.stats.avg > b.window.hi ? 'above' : b.stats.avg < b.window.lo ? 'below' : 'in'] : 'var(--text0)';
  const blockTime = (b: (typeof blocks)[number]) => {
    const done = b.stats.secs / 60;
    if (!b.stats.secs) return `— / ${mins(b.min)}`;
    return done < b.min - 0.5 ? `${mins(done)} / ${mins(b.min)}` : mins(b.min);
  };
  const showChart = $derived(blocks.length > 0 && (hasStream || blocks.some((b) => b.window)));
  const unitLabel = $derived(
    metric === 'power' ? `Targets from FTP ${ftp} W` : 'Targets from your HR zones'
  );
</script>

{#if summary.length}
  <div class="grid gap-1.5" style="grid-template-columns: repeat({summary.length}, minmax(0, 1fr))">
    {#each summary as x (x.k)}
      <div class="px-2.5 py-[9px] rounded-xl bg-bg1 flex flex-col gap-0.5">
        <span class="text-[10px] text-text2">{x.k}</span>
        <span class="text-[15px] font-medium whitespace-nowrap" style="color: {x.c}">{x.v}</span>
      </div>
    {/each}
  </div>
{/if}

{#if showChart}
  <div class="flex justify-between items-center gap-2">
    {#if metrics.length > 1}
      <div role="tablist" aria-label="Metric" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
        {#each metrics as [id, label] (id)}
          <button
            type="button"
            role="tab"
            aria-selected={view === id}
            class="h-[30px] px-2.5 border-0 rounded-lg text-[12px] font-medium whitespace-nowrap cursor-pointer {view === id ? 'bg-border text-text0' : 'bg-transparent text-text2'}"
            onclick={() => (picked = id as typeof picked)}
          >{label}</button>
        {/each}
      </div>
    {:else}
      <span class="text-[13px] font-medium">Planned vs actual</span>
    {/if}
    <span class="font-mono text-[9px] tracking-[0.06em] text-text3 text-right">{unitLabel}</span>
  </div>

  <div class="relative">
    <svg
      width="100%"
      height="170"
      viewBox="0 0 {W} 160"
      preserveAspectRatio="none"
      role="img"
      aria-label="Planned target {metric === 'power' ? 'power' : 'heart-rate'} windows for each block, with your {metric === 'power' ? 'power' : 'heart rate'} drawn over them"
      class="block"
    >
      {#each bands as z (z.zone)}
        <rect x="0" y={Y(z.hi)} width={W} height={Math.max(0, Y(z.lo) - Y(z.hi))} fill={zoneVar(z.zone)} fill-opacity="0.045"></rect>
      {/each}
      {#each blocks as b (b.i)}
        {#if b.window}
          <rect
            x={X(b.t0)}
            y={Y(b.window.hi)}
            width={Math.max(X(b.t0 + b.min) - X(b.t0) - 0.8, 1)}
            height={Math.max(Y(b.window.lo) - Y(b.window.hi), 2)}
            rx="2"
            fill={zoneVar(b.window.zone)}
            fill-opacity={b.stats.secs ? 0.2 : 0.07}
            stroke={zoneVar(b.window.zone)}
            stroke-opacity="0.7"
            stroke-dasharray="3 2"
            vector-effect="non-scaling-stroke"
          ></rect>
        {/if}
      {/each}
      {#each trace as p, k (k)}
        {#if k > 0}
          <line
            x1={X(trace[k - 1].tMin)}
            y1={Y(trace[k - 1].v)}
            x2={X(p.tMin)}
            y2={Y(p.v)}
            stroke={FIT_COLOR[p.fit]}
            stroke-width="2.2"
            stroke-linecap="round"
            vector-effect="non-scaling-stroke"
          ></line>
        {/if}
      {/each}
      {#if hrTrace}
        <polyline points={hrTrace} fill="none" stroke="var(--red)" stroke-opacity="0.75" stroke-width="1.2" stroke-dasharray="3 2" vector-effect="non-scaling-stroke"></polyline>
      {/if}
      {#if stoppedEarly}
        <line x1={X(actualMin)} y1="0" x2={X(actualMin)} y2={PLOT_H} stroke="var(--text0)" stroke-opacity="0.3" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"></line>
      {/if}
    </svg>
    <div aria-hidden="true" class="absolute right-0.5 top-0 flex flex-col pointer-events-none" style="height: {(PLOT_H / 160) * 100}%">
      {#each [...bands].reverse() as z (z.zone)}
        <span class="flex items-center font-mono text-[9px] opacity-75" style="flex: {z.hi - z.lo} 1 0; color: {zoneVar(z.zone)}">Z{z.zone}</span>
      {/each}
    </div>
  </div>
  <div class="flex justify-between font-mono text-[10px] text-text3">
    <span>0′</span>
    {#if stoppedEarly}<span>stopped {mins(actualMin)}</span>{/if}
    <span>{mins(span)}</span>
  </div>
  {#if hrTrace}
    <span class="flex items-center gap-1.5 text-[11px] text-text2">
      <span aria-hidden="true" class="w-3.5 h-0 border-t-[1.5px] border-dashed border-red"></span>{hrByZone
        ? 'Heart rate, drawn in its own zones — how hard the power felt'
        : 'Heart rate (own scale) — how hard the power felt'}
    </span>
  {/if}

  <ul class="list-none m-0 p-0 flex flex-col gap-1">
    {#each blocks as b (b.i)}
      {@const s = b.stats}
      <li class="flex gap-2.5 p-2.5 rounded-xl bg-bg1 text-text0 {s.secs ? '' : 'opacity-[0.55]'}">
          <span aria-hidden="true" class="shrink-0 w-1 self-stretch rounded-sm" style="background: {zoneVar(b.window?.zone ?? 0)}; opacity: {s.secs ? 1 : 0.35}"></span>
          <span class="flex-1 min-w-0 flex flex-col gap-[5px]">
            <span class="flex justify-between gap-2">
              <span class="text-[13px] font-medium truncate">{b.name}</span>
              <span class="font-mono text-[11px] text-text2 shrink-0">{blockTime(b)}</span>
            </span>
            {#if b.window && s.fitSecs}
              <span aria-hidden="true" class="flex h-1.5 rounded-[3px] overflow-hidden bg-border">
                <span class="block h-full" style="width: {pct(s.below, s.fitSecs)}%; background: {FIT_COLOR.below}"></span>
                <span class="block h-full" style="width: {pct(s.inn, s.fitSecs)}%; background: {FIT_COLOR.in}"></span>
                <span class="block h-full" style="width: {pct(s.above, s.fitSecs)}%; background: {FIT_COLOR.above}"></span>
              </span>
            {/if}
            <span class="flex justify-between gap-2 text-[11px] text-text2">
              <span>{b.window?.label ?? 'No target'}</span>
              <span>
                avg <span style="color: {avgColor(b)}">{s.avg != null ? `${s.avg} ${unit}` : '—'}</span>{b.window && s.fitSecs ? ` · ${pct(s.inn, s.fitSecs)}% in` : ''}
              </span>
            </span>
          </span>
      </li>
    {/each}
  </ul>

  {#if hasStream}
    <div class="flex gap-3 flex-wrap items-center text-[11px] text-text2">
      <span class="flex items-center gap-[5px]"><span aria-hidden="true" class="w-2.5 h-1 rounded-sm bg-green"></span>In target</span>
      <span class="flex items-center gap-[5px]"><span aria-hidden="true" class="w-2.5 h-1 rounded-sm bg-amber"></span>Above</span>
      <span class="flex items-center gap-[5px]"><span aria-hidden="true" class="w-2.5 h-1 rounded-sm" style="background: {FIT_COLOR.below}"></span>Below</span>
    </div>
  {/if}
{/if}
