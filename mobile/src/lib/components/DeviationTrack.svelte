<script lang="ts">
  import { zScoreCssColor } from '$lib/scoreColors';

  // Center-anchored Z-score visualisation.
  //
  // The track's exact center represents the 7-day EWMA baseline. A subtle
  // central band marks the "normal range" (-0.5 to +0.5 SD). Today's reading
  // is rendered as a colored dot positioned by its z-score; the dot's color
  // is driven by the same band rule as `TrendIndicator` (and inverted for
  // metrics where lower is better, e.g. RHR, body temp).
  //
  // `range` controls how many SDs map to each side of the track (default ±2.5).
  // Z-scores beyond the range are clamped to the edge so the dot never
  // disappears off-screen, but the color still reflects the true band.
  let {
    z,
    inverted = false,
    range = 2.5,
    height = 6
  } = $props<{
    z: number | null | undefined;
    inverted?: boolean;
    range?: number;
    height?: number;
  }>();

  const hasZ = $derived(z != null && Number.isFinite(Number(z)));
  const rawZ = $derived(hasZ ? Number(z) : 0);
  const clampedZ = $derived(Math.max(-range, Math.min(range, rawZ)));

  // -range -> 0%, 0 -> 50%, +range -> 100%
  const dotLeftPct = $derived(((clampedZ + range) / (2 * range)) * 100);
  // Normal range band: -0.5 to +0.5 SD on the same scale.
  const normalLeftPct = $derived(((-0.5 + range) / (2 * range)) * 100);
  const normalWidthPct = $derived((1 / (2 * range)) * 100);

  const dotColor = $derived(hasZ ? zScoreCssColor(rawZ, inverted) : 'var(--text2)');
  const dotSize = $derived(height + 2);
</script>

<div class="relative w-full" style="height: {dotSize}px;">
  <!-- Track rail: contrasts with page bg; ±0.5 SD band centered on midpoint (baseline) -->
  <div
    class="absolute left-0 right-0 top-1/2 z-0 -translate-y-1/2 overflow-hidden rounded-full bg-slate-800/95 ring-1 ring-inset ring-white/[0.14]"
    style="height: {height}px;"
  >
    <!-- Normal range (±0.5 SD) — same coordinate system as the dot -->
    <div
      class="absolute top-0 bottom-0 z-[1] rounded-[2px] bg-slate-500/65 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.18)]"
      style="left: {normalLeftPct}%; width: {normalWidthPct}%;"
    ></div>
  </div>

  <!-- 1px baseline notch (z=0) intersecting the rail -->
  <div
    class="pointer-events-none absolute left-1/2 top-1/2 z-[2] h-[calc(100%-2px)] w-px max-h-[14px] -translate-x-1/2 -translate-y-1/2 bg-white/70"
    aria-hidden="true"
  ></div>

  <!-- Today's value -->
  {#if hasZ}
    <div
      class="absolute top-1/2 z-[3] rounded-full shadow-[0_0_0_2px_var(--bg1,#0F0F1A),0_1px_2px_rgba(0,0,0,0.4)] transition-[left] duration-200"
      style="left: {dotLeftPct}%; width: {dotSize}px; height: {dotSize}px; background: {dotColor}; transform: translate(-50%, -50%);"
      aria-hidden="true"
    ></div>
  {/if}
</div>
