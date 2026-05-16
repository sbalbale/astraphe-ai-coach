<script lang="ts">
  let { value, size = 140, color = null } = $props<{
    value: number;
    size?: number;
    color?: string | null;
  }>();

  let canvas: HTMLCanvasElement;

  $effect(() => {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr; 
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);
    
    const cx = size / 2;
    const cy = size / 2 + (size * 0.07); // Adjusted offset
    const r = size * 0.37;
    const startAngle = Math.PI * 0.75;
    const endAngle = Math.PI * 2.25;
    
    // Track
    ctx.beginPath(); 
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)'; 
    ctx.lineWidth = size * 0.07; 
    ctx.lineCap = 'round'; 
    ctx.stroke();
    
    // Value arc
    const valAngle = startAngle + (Math.min(100, Math.max(0, value)) / 100) * (endAngle - startAngle);
    
    if (color) {
      ctx.strokeStyle = color;
    } else {
      const grad = ctx.createLinearGradient(cx - r, cy, cx + r, cy);
      grad.addColorStop(0, '#F07178'); 
      grad.addColorStop(0.4, '#FFCB88'); 
      grad.addColorStop(0.7, '#00C8A8'); 
      grad.addColorStop(1, '#4621FF');
      ctx.strokeStyle = grad;
    }
    
    ctx.beginPath(); 
    ctx.arc(cx, cy, r, startAngle, valAngle);
    ctx.lineWidth = size * 0.07; 
    ctx.lineCap = 'round'; 
    ctx.stroke();
    
    // Dot at end
    const ex = cx + Math.cos(valAngle) * r;
    const ey = cy + Math.sin(valAngle) * r;
    ctx.beginPath(); 
    ctx.arc(ex, ey, size * 0.035, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; 
    ctx.fill();
  });
</script>

<canvas bind:this={canvas} style="width: {size}px; height: {size}px;"></canvas>
