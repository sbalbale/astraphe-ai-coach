<script lang="ts">
  import {
    CHART_ATL_FILL_ACTIVE,
    CHART_ATL_FILL_REST,
    CHART_CTL_STROKE,
    formCssColor
  } from '$lib/scoreColors';

  const CHART_PAD = { t: 15, b: 24, l: 36, r: 15 } as const;

  let { data, height = 100 } = $props<{
    data: { day: string; date?: string; atl: number; ctl: number; tsb?: number; daily_tss?: number }[];
    height?: number;
  }>();

  let canvas: HTMLCanvasElement;
  let chartRoot: HTMLDivElement;
  let scrollHost: HTMLDivElement;
  let chartWidth = $state(0);
  let selectedIdx = $state<number | null>(null);
  let tooltipLayout = $state<{ x: number; y: number; flipLeft: boolean } | null>(null);
  let touchStart: { x: number; y: number } | null = null;

  function updateTooltipLayout() {
    if (selectedIdx === null || !canvas || !scrollHost) {
      tooltipLayout = null;
      return;
    }

    const canvasRect = canvas.getBoundingClientRect();
    const scrollRect = scrollHost.getBoundingClientRect();
    const denom = Math.max(1, data.length - 1);
    const pct = selectedIdx / denom;
    const plotW = canvasRect.width - CHART_PAD.l - CHART_PAD.r;
    const pointXInCanvas = CHART_PAD.l + pct * plotW;
    const anchorX = canvasRect.left + pointXInCanvas;
    const anchorY = canvasRect.top + 4;
    const visibleMid = scrollRect.left + scrollRect.width / 2;

    tooltipLayout = {
      x: anchorX,
      y: anchorY,
      flipLeft: anchorX > visibleMid
    };
  }

  function tsbColor(tsb: number | undefined | null): string {
    if (tsb == null || !Number.isFinite(tsb)) return 'var(--text2)';
    return formCssColor(tsb);
  }

  const axisDateFmtNumeric = new Intl.DateTimeFormat(undefined, {
    month: 'numeric',
    day: 'numeric',
    timeZone: 'UTC'
  });

  const axisDateFmtShort = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC'
  });

  const tooltipDateFmt = new Intl.DateTimeFormat(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC'
  });

  function parseDateLike(s: string): Date | null {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s.trim());
    if (m) {
      const y = Number(m[1]);
      const mo = Number(m[2]);
      const d = Number(m[3]);
      if (Number.isFinite(y) && Number.isFinite(mo) && Number.isFinite(d)) {
        return new Date(Date.UTC(y, mo - 1, d));
      }
    }

    const ms = Date.parse(s);
    if (!Number.isFinite(ms)) return null;
    return new Date(ms);
  }

  function formatAxisDate(d: { day?: string; date?: string }, useCompact: boolean): string {
    if (d.date) {
      const parsed = parseDateLike(d.date);
      if (parsed) return useCompact ? axisDateFmtNumeric.format(parsed) : axisDateFmtShort.format(parsed);
    }
    return d.day || '';
  }

  function formatTooltipDate(d: { day?: string; date?: string }): string {
    if (d.date) {
      const parsed = parseDateLike(d.date);
      if (parsed) return tooltipDateFmt.format(parsed);
    }
    return d.day || '';
  }

  function uniqueSortedIndices(nums: number[]): number[] {
    const sorted = [...nums].sort((a, b) => a - b);
    const out: number[] = [];
    let prev = -1;
    for (const x of sorted) {
      if (x !== prev) out.push(x);
      prev = x;
    }
    return out;
  }

  /** X-axis label indices: sparse on long ranges to avoid overlap. */
  function getXAxisLabelIndices(n: number): number[] {
    if (n <= 0) return [];
    if (n <= 8) return Array.from({ length: n }, (_, i) => i);
    if (n < 22) {
      const step = Math.ceil(n / 5);
      const acc: number[] = [0, n - 1];
      for (let i = 0; i < n; i += step) acc.push(i);
      return uniqueSortedIndices(acc);
    }
    const acc: number[] = [0, n - 1];
    for (let i = 7; i < n - 1; i += 7) acc.push(i);
    acc.push(Math.floor((n - 1) / 2));
    return uniqueSortedIndices(acc);
  }

  function indexFromLocalX(localX: number, plotW: number, denom: number, padL: number): number {
    const idx = Math.round(((localX - padL) / plotW) * denom);
    return Math.min(Math.max(idx, 0), data.length - 1);
  }

  function handlePointerLocalX(clientX: number) {
    if (!canvas || data.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - CHART_PAD.l - CHART_PAD.r;
    const denom = Math.max(1, data.length - 1);
    const x = clientX - rect.left;
    const idx = indexFromLocalX(x, plotW, denom, CHART_PAD.l);
    selectedIdx = idx;
    updateTooltipLayout();
  }

  function handleMouseMove(e: MouseEvent) {
    handlePointerLocalX(e.clientX);
  }

  function onTouchStart(e: TouchEvent) {
    const t = e.touches[0];
    if (!t) return;
    touchStart = { x: t.clientX, y: t.clientY };
  }

  function onTouchEnd(e: TouchEvent) {
    const t = e.changedTouches[0];
    if (!t || !touchStart) {
      touchStart = null;
      return;
    }
    const dx = Math.abs(t.clientX - touchStart.x);
    const dy = Math.abs(t.clientY - touchStart.y);
    touchStart = null;
    if (dx > 14 || dy > 14) return;
    handlePointerLocalX(t.clientX);
  }

  function onTouchCancel() {
    touchStart = null;
  }

  function onDocumentPointerDown(e: PointerEvent) {
    if (selectedIdx === null) return;
    const target = e.target as Node;
    if (scrollHost?.contains(target)) return;
    selectedIdx = null;
    tooltipLayout = null;
  }

  $effect(() => {
    if (!canvas) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) chartWidth = w;
      updateTooltipLayout();
    });
    ro.observe(canvas);
    const initial = canvas.getBoundingClientRect().width;
    if (initial > 0) chartWidth = initial;
    return () => ro.disconnect();
  });

  $effect(() => {
    document.addEventListener('pointerdown', onDocumentPointerDown);
    return () => document.removeEventListener('pointerdown', onDocumentPointerDown);
  });

  $effect(() => {
    selectedIdx;
    chartWidth;
    updateTooltipLayout();
  });

  $effect(() => {
    if (!scrollHost) return;
    const onScroll = () => updateTooltipLayout();
    scrollHost.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      scrollHost.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  });

  $effect(() => {
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = chartWidth > 0 ? chartWidth : canvas.offsetWidth;
    const H = height;
    const useCompactAxis = W < 360;

    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const days = data.length;
    const denom = Math.max(1, days - 1);
    const plotW = W - CHART_PAD.l - CHART_PAD.r;
    const plotH = H - CHART_PAD.t - CHART_PAD.b;

    const allVals = data.flatMap((d: any) => [d.atl, d.ctl]);
    const min = 0;
    const max = Math.max(...allVals, 20) + 15;

    const px = (i: number) => CHART_PAD.l + (i / denom) * plotW;
    const py = (v: number) => CHART_PAD.t + plotH - ((v - min) / (max - min)) * plotH;

    // Grid lines
    [0, 25, 50, 75, 100].forEach((v) => {
      if (v > max) return;
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(255,255,255,0.05)';
      ctx.lineWidth = 1;
      ctx.moveTo(CHART_PAD.l, py(v));
      ctx.lineTo(CHART_PAD.l + plotW, py(v));
      ctx.stroke();

      ctx.font = '9px "Space Mono", monospace';
      ctx.fillStyle = 'rgba(240,240,255,0.3)';
      ctx.textAlign = 'right';
      ctx.fillText(v.toString(), CHART_PAD.l - 4, py(v) + 3);
    });

    if (selectedIdx !== null) {
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.setLineDash([4, 4]);
      ctx.moveTo(px(selectedIdx), CHART_PAD.t);
      ctx.lineTo(px(selectedIdx), H - CHART_PAD.b);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    const bw = Math.max(4, (plotW / days) * 0.4);
    data.forEach((d: any, i: number) => {
      const bh = ((d.atl - min) / (max - min)) * plotH;
      ctx.fillStyle = selectedIdx === i ? CHART_ATL_FILL_ACTIVE : CHART_ATL_FILL_REST;
      ctx.fillRect(px(i) - bw / 2, py(d.atl), bw, bh);
    });

    // CTL line only; ATL is rendered as bars above.
    const drawLine = (key: 'ctl', color: string) => {
      ctx.beginPath();
      data.forEach((d: any, i: number) => (i === 0 ? ctx.moveTo(px(i), py(d[key])) : ctx.lineTo(px(i), py(d[key]))));
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.lineJoin = 'round';
      ctx.stroke();

      data.forEach((d: any, i: number) => {
        ctx.beginPath();
        ctx.arc(px(i), py(d[key]), selectedIdx === i ? 4 : 3, 0, Math.PI * 2);
        ctx.fillStyle = selectedIdx === i ? '#fff' : color;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.fill();
        ctx.stroke();
      });
    };

    drawLine('ctl', CHART_CTL_STROKE);

    const baseLabels = getXAxisLabelIndices(days);
    const labelIndices =
      selectedIdx !== null && !baseLabels.includes(selectedIdx)
        ? uniqueSortedIndices([...baseLabels, selectedIdx])
        : baseLabels;

    ctx.font = '9px "Space Grotesk", sans-serif';
    ctx.textAlign = 'center';
    for (const i of labelIndices) {
      const d = data[i];
      if (!d) continue;
      ctx.fillStyle = selectedIdx === i ? '#fff' : 'rgba(240,240,255,0.35)';
      ctx.fillText(formatAxisDate(d, useCompactAxis), px(i), H - 6);
    }
  });
</script>

<div class="relative">
  <div
    bind:this={scrollHost}
    class="overflow-x-auto overflow-y-visible snap-x snap-mandatory overscroll-x-contain [-webkit-overflow-scrolling:touch]"
  >
    <div
      bind:this={chartRoot}
      class="relative group min-w-[600px] w-full snap-start"
      role="presentation"
      onpointerleave={() => {
        selectedIdx = null;
        tooltipLayout = null;
      }}
    >
    <canvas
      bind:this={canvas}
      class="w-full cursor-crosshair touch-pan-x"
      style="height: {height}px;"
      onmousemove={handleMouseMove}
      ontouchstart={onTouchStart}
      ontouchend={onTouchEnd}
      ontouchcancel={onTouchCancel}
    ></canvas>

    </div>
  </div>

  {#if selectedIdx !== null && data[selectedIdx] && tooltipLayout}
    {@const d = data[selectedIdx]}
    {@const longDate = formatTooltipDate(d)}
    {@const ctlR = Math.round(d.ctl)}
    {@const atlR = Math.round(d.atl)}
    <div
      class="fixed z-50 w-max max-w-[min(280px,calc(100vw-16px))] pointer-events-none {tooltipLayout.flipLeft
        ? '-translate-x-[calc(100%+6px)]'
        : 'translate-x-[6px]'}"
      style="left: {Math.round(tooltipLayout.x)}px; top: {Math.round(tooltipLayout.y)}px;"
    >
        <div
          class="bg-glass border border-white/10 rounded-lg p-2 shadow-xl backdrop-blur-md animate-in fade-in zoom-in duration-200 whitespace-normal"
        >
          <p class="text-[11px] text-text1 font-medium leading-snug mb-1">
            {longDate || 'Details'}: {ctlR} CTL / {atlR} ATL
          </p>
          {#if d.daily_tss !== undefined && d.daily_tss > 0}
            <p class="text-[11px] font-mono text-text1 mt-0.5">TSS: {Math.round(d.daily_tss)}</p>
          {/if}
          {#if d.tsb !== undefined}
            <div class="flex items-center gap-2 pt-1 border-t border-white/5 mt-1">
              <span class="text-[11px] text-text1"
                >Form (TSB):
                <span class="font-bold" style="color: {tsbColor(d.tsb)}"
                  >{d.tsb >= 0 ? '+' : ''}{Math.round(d.tsb)}</span
                ></span
              >
            </div>
          {/if}
        </div>
    </div>
  {/if}
</div>
