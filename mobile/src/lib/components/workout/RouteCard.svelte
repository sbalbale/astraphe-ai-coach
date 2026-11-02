<script lang="ts">
  /** GPS route drawn as a single accent line, fitted to the card (workout detail design). */
  let { latlng }: { latlng: [number, number][] } = $props();

  const W = 350;
  const H = 150;
  const PAD = 20;

  const route = $derived.by(() => {
    const pts = latlng.filter((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]));
    if (pts.length < 2) return null;
    const step = Math.max(1, Math.floor(pts.length / 250));
    const sampled = pts.filter((_, i) => i % step === 0 || i === pts.length - 1);

    const meanLat = sampled.reduce((a, p) => a + p[0], 0) / sampled.length;
    const lonScale = Math.cos((meanLat * Math.PI) / 180);
    const xs = sampled.map((p) => p[1] * lonScale);
    const ys = sampled.map((p) => -p[0]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = Math.max(maxX - minX, 1e-9);
    const spanY = Math.max(maxY - minY, 1e-9);
    const scale = Math.min((W - PAD * 2) / spanX, (H - PAD * 2) / spanY);
    const offX = (W - spanX * scale) / 2;
    const offY = (H - spanY * scale) / 2;
    const proj = sampled.map((_, i) => ({ x: offX + (xs[i] - minX) * scale, y: offY + (ys[i] - minY) * scale }));
    const d = proj.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    return { d, start: proj[0] };
  });
</script>

{#if route}
  <div role="img" aria-label="Route map" class="h-[150px] rounded-[20px] bg-bg1 border border-border overflow-hidden">
    <svg viewBox="0 0 {W} {H}" width="100%" height="150" preserveAspectRatio="xMidYMid meet" class="block" aria-hidden="true">
      <path d={route.d} fill="none" stroke="var(--blue)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></path>
      <circle cx={route.start.x} cy={route.start.y} r="5" fill="var(--bg0)" stroke="var(--blue)" stroke-width="2.5"></circle>
    </svg>
  </div>
{/if}
