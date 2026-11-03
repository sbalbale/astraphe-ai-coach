<script lang="ts">
  /** Training load (design: WTrends): weekly fitness line + area, dashed fatigue, form bars. */
  import { format } from 'date-fns';
  import { formCssColor } from '$lib/scoreColors';
  import type { WeekBucket } from './trendsWide';

  let {
    weeks,
    selected,
    onselect
  }: { weeks: WeekBucket[]; selected: number; onselect: (i: number) => void } = $props();

  const W = 580;
  const H = 210;
  const BASE = 180;
  const n = $derived(weeks.length);
  const xAt = (j: number) => (n <= 1 ? W / 2 : (j + 0.5) * (W / n));

  const scale = $derived.by(() => {
    const vals = weeks.flatMap((w) => (w.ctl == null ? [] : [w.ctl, w.atl ?? w.ctl]));
    if (!vals.length) return null;
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const pad = Math.max((hi - lo) * 0.15, 3);
    return { lo: lo - pad, hi: hi + pad };
  });
  const yL = (v: number) => (scale ? BASE - ((v - scale.lo) / Math.max(scale.hi - scale.lo, 1)) * 170 : BASE);

  const pts = $derived(weeks.map((w, j) => ({ j, w })).filter((p) => p.w.ctl != null));
  /** Form bar width; the lines run from the first bar's left edge to the last bar's right edge. */
  const bw = $derived(Math.max((W / Math.max(n, 1)) * 0.35, 3));
  const lineX = (k: number) => {
    const x = xAt(pts[k].j);
    if (pts.length > 1 && k === 0) return x - bw / 2;
    if (pts.length > 1 && k === pts.length - 1) return x + bw / 2;
    return x;
  };
  const ctlPts = $derived(pts.map((p, k) => `${lineX(k).toFixed(1)},${yL(p.w.ctl!).toFixed(1)}`));
  const atlPts = $derived(pts.map((p, k) => `${lineX(k).toFixed(1)},${yL(p.w.atl ?? p.w.ctl!).toFixed(1)}`).join(' '));
  const area = $derived(
    pts.length > 1
      ? `M${ctlPts[0]} L${ctlPts.join(' L')} L${lineX(pts.length - 1).toFixed(1)},${BASE} L${lineX(0).toFixed(1)},${BASE} Z`
      : ''
  );
  const formBars = $derived(
    pts.map((p) => {
      const f = p.w.ctl! - (p.w.atl ?? p.w.ctl!);
      const h = Math.min(Math.abs(f) * 1.6, 28);
      return { x: xAt(p.j) - bw / 2, w: bw, y: f >= 0 ? BASE - h : BASE, h: Math.max(h, 1), c: formCssColor(f) };
    })
  );

  const sel = $derived(weeks[selected]);
  const weekLabel = (w: WeekBucket) => (w.current ? 'This week' : `Week of ${format(w.start, 'd MMM')}`);
  const readout = $derived.by(() => {
    if (!sel || sel.ctl == null) return sel ? `${sel.current ? 'THIS WEEK' : `WK OF ${format(sel.start, 'd MMM')}`} · NO LOAD DATA`.toUpperCase() : '';
    const form = sel.ctl - (sel.atl ?? sel.ctl);
    const head = sel.current ? 'TODAY' : `WK OF ${format(sel.start, 'd MMM').toUpperCase()}`;
    return `${head} · FITNESS ${sel.ctl.toFixed(1)} · FATIGUE ${(sel.atl ?? 0).toFixed(1)} · FORM ${form >= 0 ? '+' : ''}${form.toFixed(1)}`;
  });
  const pctX = $derived(((xAt(selected) / W) * 100).toFixed(2));
  const span = $derived(weeks.length ? `${format(weeks[0].start, 'd MMM').toUpperCase()} → NOW` : '');
</script>

<section aria-label="Training load" class="bg-bg2 border border-border rounded-[24px] px-5 pt-[18px] pb-3.5 flex flex-col gap-2.5">
  <div class="flex justify-between items-baseline gap-3">
    <h2 class="m-0 font-display font-normal text-[26px]">Training load</h2>
    <span aria-live="polite" class="font-mono text-[11px] text-text1 truncate">{readout}</span>
  </div>
  <div class="relative h-[210px]">
    <svg width="100%" height={H} viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="Fitness and fatigue by week, with form bars" class="block">
      {#each [40, 90, 140] as gy (gy)}<line x1="0" y1={gy} x2={W} y2={gy} class="stroke-bg3"></line>{/each}
      <line x1="0" y1={BASE} x2={W} y2={BASE} class="stroke-popover-border"></line>
      {#each formBars as f, i (i)}
        <rect x={f.x.toFixed(1)} y={f.y.toFixed(1)} width={f.w.toFixed(1)} height={f.h.toFixed(1)} rx="1.5" fill={f.c} fill-opacity="0.55"></rect>
      {/each}
      {#if area}<path d={area} class="fill-blue" fill-opacity="0.10"></path>{/if}
      {#if pts.length > 1}
        <polyline points={atlPts} fill="none" class="stroke-chartAtl" stroke-width="1.5" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"></polyline>
        <polyline points={ctlPts.join(' ')} fill="none" class="stroke-blue" stroke-width="2.2" vector-effect="non-scaling-stroke"></polyline>
      {/if}
      <line x1={xAt(selected)} y1="0" x2={xAt(selected)} y2="196" class="stroke-text0" stroke-opacity="0.35" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"></line>
    </svg>
    <div class="absolute inset-0 flex">
      {#each weeks as w, i (i)}
        <button
          type="button"
          aria-label="{weekLabel(w)}: {w.ctl == null ? 'no load data' : `fitness ${w.ctl.toFixed(1)}, fatigue ${(w.atl ?? 0).toFixed(1)}`}"
          aria-pressed={i === selected}
          class="flex-1 h-full p-0 border-0 bg-transparent cursor-pointer hover:bg-glass"
          onclick={() => onselect(i)}
        ></button>
      {/each}
    </div>
    {#if sel?.ctl != null}
      <span aria-hidden="true" class="absolute w-2.5 h-2.5 rounded-full -ml-[5px] -mt-[5px] pointer-events-none bg-blue shadow-[0_0_0_3px_theme(colors.bg2)]" style="left: {pctX}%; top: {((yL(sel.ctl) / H) * 100).toFixed(2)}%"></span>
      <span aria-hidden="true" class="absolute w-2.5 h-2.5 rounded-full -ml-[5px] -mt-[5px] pointer-events-none bg-text2 shadow-[0_0_0_3px_theme(colors.bg2)]" style="left: {pctX}%; top: {((yL(sel.atl ?? sel.ctl) / H) * 100).toFixed(2)}%"></span>
    {/if}
  </div>
  <div class="flex gap-[18px] text-[11px] text-text2">
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 bg-chartCtl"></span>Fitness (42d)</span>
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 border-t-2 border-dashed border-chartAtl"></span>Fatigue (7d)</span>
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2 h-2 rounded-sm bg-green opacity-60"></span>Form</span>
    <span class="ml-auto font-mono">{span}</span>
  </div>
</section>
