<script lang="ts">
  import * as d3 from 'd3';
  import type { RowingInterval, ZoneDef } from '$lib/services/activityService';
  import { formatHR } from '$lib/utils/formatters';
  import { formatPaceWithSuffix, paceChartTitle } from '$lib/utils/paceChart';
  import { hrZoneColorForBpm } from '$lib/hrZoneDisplay';
  import {
    clampPaceSeries,
    formatPaceAxisTick,
    invertedPaceYScale,
  } from '$lib/utils/paceChart';

  let { intervals, zones = [] }: { intervals: RowingInterval[]; zones?: ZoneDef[] } = $props();

  const MARGIN = { top: 24, right: 8, bottom: 28, left: 40 };
  const CHART_H = 100;
  const svgH = CHART_H + MARGIN.top + MARGIN.bottom;

  let chartWidth = $state(300);
  let chartEl: HTMLDivElement | undefined = $state();
  let hoveredIdx = $state<number | null>(null);

  const innerW = $derived(Math.max(1, chartWidth - MARGIN.left - MARGIN.right));

  type BarChartModel = {
    id: 'pace' | 'hr';
    title: string;
    unitLabel: string;
    subtitle: string;
    hoverLine: (idx: number) => string;
    bars: { x: number; width: number; height: number; color: string; idx: number }[];
    yScale: d3.ScaleLinear<number, number>;
    yTickFormat: (v: d3.NumberValue) => string;
    xLabels: { x: number; label: string }[];
  };

  const chartModels = $derived.by((): BarChartModel[] => {
    if (intervals.length < 2 || innerW <= 0) return [];
    const list: BarChartModel[] = [];
    const n = intervals.length;
    const xBand = d3
      .scaleBand<number>()
      .domain(intervals.map((_, i) => i))
      .range([0, innerW])
      .paddingInner(0.15)
      .paddingOuter(0.08);
    const bw = xBand.bandwidth();

    const paceVals = intervals
      .map((iv) => iv.pace_per_500m)
      .filter((p): p is number => p != null && Number.isFinite(p) && p > 0);
    if (paceVals.length >= 2) {
      const { lo: pLo, hi: pHi } = clampPaceSeries(paceVals);
      const yS = invertedPaceYScale(pLo, pHi, CHART_H, 0.12);
      const best = d3.min(paceVals) ?? 0;
      const avg = paceVals.reduce((a, b) => a + b, 0) / paceVals.length;
      const bars = intervals.map((iv, i) => {
        const raw = iv.pace_per_500m;
        const p =
          raw != null && raw > 0 ? Math.min(pHi, Math.max(pLo, raw)) : null;
        const y0 = CHART_H;
        const y1 = p != null ? yS(p) : CHART_H;
        const x = xBand(i) ?? 0;
        return {
          x,
          width: bw,
          height: Math.max(0, y0 - y1),
          color: '#00C8A8',
          idx: i,
        };
      });
      list.push({
        id: 'pace',
        title: paceChartTitle('row'),
        unitLabel: '/500m',
        subtitle: `Best ${formatPaceWithSuffix(best, 'row')} · Avg ${formatPaceWithSuffix(avg, 'row')} · per split`,
        hoverLine: (idx) => {
          const iv = intervals[idx];
          const p = iv.pace_per_500m;
          return `Split ${iv.split_number} · ${formatPaceWithSuffix(p, 'row')}`;
        },
        bars,
        yScale: yS,
        yTickFormat: formatPaceAxisTick,
        xLabels: labelTicks(n, xBand),
      });
    }

    const hrVals = intervals
      .map((iv) => iv.average_heartrate)
      .filter((h): h is number => h != null && Number.isFinite(h));
    if (hrVals.length >= 2) {
      let yMin = d3.min(hrVals) ?? 0;
      let yMax = d3.max(hrVals) ?? 1;
      const pad = Math.max(4, (yMax - yMin) * 0.12);
      yMin -= pad;
      yMax += pad;
      const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);
      const avg = hrVals.reduce((a, b) => a + b, 0) / hrVals.length;
      const max = d3.max(hrVals) ?? 0;
      const bars = intervals.map((iv, i) => {
        const h = iv.average_heartrate;
        const y0 = CHART_H;
        const y1 = h != null ? yS(h) : CHART_H;
        const x = xBand(i) ?? 0;
        return {
          x,
          width: bw,
          height: Math.max(0, y0 - y1),
          color: hrZoneColorForBpm(zones, h),
          idx: i,
        };
      });
      list.push({
        id: 'hr',
        title: 'Heart Rate',
        unitLabel: 'bpm',
        subtitle: `Avg ${Math.round(avg)} bpm · Max ${Math.round(max)} bpm · per split`,
        hoverLine: (idx) => {
          const iv = intervals[idx];
          const h = iv.average_heartrate;
          return `Split ${iv.split_number} · ${h != null ? formatHR(h) : '—'} bpm`;
        },
        bars,
        yScale: yS,
        yTickFormat: (v) => String(Math.round(Number(v))),
        xLabels: labelTicks(n, xBand),
      });
    }

    return list;
  });

  function labelTicks(
    n: number,
    xBand: d3.ScaleBand<number>
  ): { x: number; label: string }[] {
    if (n <= 6) {
      return intervals.map((iv, i) => ({
        x: (xBand(i) ?? 0) + xBand.bandwidth() / 2,
        label: String(iv.split_number),
      }));
    }
    const indices = [0, Math.floor(n / 2), n - 1];
    return indices.map((i) => ({
      x: (xBand(i) ?? 0) + xBand.bandwidth() / 2,
      label: String(intervals[i].split_number),
    }));
  }

  let axisYRefs = $state<Partial<Record<'pace' | 'hr', SVGGElement | undefined>>>({});

  $effect(() => {
    axisYRefs;
    for (const c of chartModels) {
      const gy = axisYRefs[c.id];
      if (gy) {
        const axis = d3
          .axisLeft(c.yScale)
          .ticks(4)
          .tickFormat(c.yTickFormat)
          .tickSize(0)
          .tickSizeOuter(0);
        const sel = d3.select(gy);
        sel.call(axis);
        sel.select('.domain').remove();
        sel
          .selectAll('.tick text')
          .attr('dx', -6)
          .attr('font-size', 9)
          .attr('font-family', 'monospace')
          .attr('fill', 'var(--text2)');
      }
    }
  });

  $effect(() => {
    const node = chartEl;
    if (!node) return;
    const ro = new ResizeObserver(() => {
      chartWidth = node.clientWidth || 300;
    });
    ro.observe(node);
    chartWidth = node.clientWidth || 300;
    return () => ro.disconnect();
  });
</script>

<div
  class="rounded-2xl bg-glass2 border border-border p-3 space-y-4 touch-none select-none"
  bind:this={chartEl}
  role="presentation"
>
  <p class="text-[11px] font-semibold text-text1 flex items-center gap-1.5">
    <span class="w-1.5 h-1.5 rounded-full bg-teal inline-block"></span>
    Split Charts
  </p>
  <p class="text-[10px] text-text2 font-mono -mt-2">
    Strava did not provide usable pace streams for this row; charts use device lap splits.
  </p>

  {#if chartModels.length === 0}
    <p class="text-[12px] text-text2 font-mono text-center py-6">No split chart data.</p>
  {:else}
    {#each chartModels as c (c.id)}
      <div>
        <p class="text-[11px] font-semibold text-text0 mb-0.5">{c.title}</p>
        <p class="text-[10px] font-mono text-text2 h-4 mb-0.5">
          {hoveredIdx === null ? c.subtitle : c.hoverLine(hoveredIdx)}
        </p>
        <svg
          class="block w-full"
          width="100%"
          height={svgH}
          viewBox="0 0 {chartWidth} {svgH}"
          preserveAspectRatio="none"
        >
          <text
            x={6}
            y={MARGIN.top - 14}
            text-anchor="start"
            font-size="9"
            fill="var(--text2)"
            font-family="monospace"
          >
            {c.unitLabel}
          </text>

          <g transform="translate({MARGIN.left},{MARGIN.top})">
            {#each c.bars as bar (bar.idx)}
              <rect
                x={bar.x}
                y={CHART_H - bar.height}
                width={bar.width}
                height={bar.height}
                fill={bar.color}
                opacity={hoveredIdx === null || hoveredIdx === bar.idx ? 0.95 : 0.45}
                rx="2"
                role="presentation"
                onpointerenter={() => (hoveredIdx = bar.idx)}
                onpointerleave={() => (hoveredIdx = null)}
              />
            {/each}
          </g>

          <g transform="translate({MARGIN.left},{MARGIN.top + CHART_H + 6})">
            {#each c.xLabels as tick (tick.label + tick.x)}
              <text
                x={tick.x}
                y={0}
                text-anchor="middle"
                font-size="9"
                fill="var(--text2)"
                font-family="monospace"
              >
                {tick.label}
              </text>
            {/each}
          </g>

          <g
            bind:this={axisYRefs[c.id]}
            transform="translate({MARGIN.left},{MARGIN.top})"
          ></g>
        </svg>
      </div>
    {/each}
  {/if}
</div>
