<script lang="ts">
  let { data, size = 80 } = $props<{
    data: { pct: number; color: string }[];
    size?: number;
  }>();

  let canvas: HTMLCanvasElement;

  $effect(() => {
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr; 
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);
    
    const cx = size / 2;
    const cy = size / 2;
    const r = size / 2 - 6;
    const iR = r * 0.62;
    
    let start = -Math.PI / 2;
    
    data.forEach(({ pct, color }: { pct: number, color: string }) => {
      const angle = (pct / 100) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, r, start, start + angle);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      start += angle;
    });
    
    ctx.beginPath();
    ctx.arc(cx, cy, iR, 0, Math.PI * 2);
    ctx.fillStyle = '#0F0F1A'; // Matches --bg1 in design system
    ctx.fill();
  });
</script>

<canvas bind:this={canvas} style="width: {size}px; height: {size}px;"></canvas>
