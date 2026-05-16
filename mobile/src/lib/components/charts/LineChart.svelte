<script lang="ts">
  let { data, color = '#4621FF', fill = true, height = 80, yKey, labels, unit = '', formatValue, getValueColor } = $props<{
    data: any[];
    color?: string;
    fill?: boolean;
    height?: number;
    yKey?: string;
    labels?: string[];
    unit?: string;
    formatValue?: (val: any) => string;
    getValueColor?: (val: number) => string;
  }>();

  let canvas: HTMLCanvasElement;
  let selectedIdx = $state<number | null>(null);

  $effect(() => {
    if (!canvas || !data || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = height;
    
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    
    const vals = yKey ? data.map((d: any) => d[yKey]) : data;
    const min = Math.min(...vals), max = Math.max(...vals);
    const range = max - min || 1;
    const pad = { t: 8, b: labels ? 20 : 8, l: 8, r: 8 };
    const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    
    const px = (i: number) => pad.l + (i / (vals.length - 1)) * plotW;
    const py = (v: number) => pad.t + plotH - ((v - min) / range) * plotH;
    
    if (fill) {
      const grad = ctx.createLinearGradient(0, pad.t + plotH, 0, pad.t);
      if (getValueColor) {
        [0, 0.25, 0.5, 0.75, 1].forEach(stop => {
          const v = min + stop * range;
          grad.addColorStop(stop, getValueColor(v) + '4D'); // ~0.3 opacity
        });
      } else {
        grad.addColorStop(1, color + '4D');
        grad.addColorStop(0, color + '00');
      }
      ctx.beginPath();
      vals.forEach((v: number, i: number) => i === 0 ? ctx.moveTo(px(i), py(v)) : ctx.lineTo(px(i), py(v)));
      ctx.lineTo(px(vals.length - 1), pad.t + plotH);
      ctx.lineTo(px(0), pad.t + plotH);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();
    }
    
    // Interaction Line
    if (selectedIdx !== null) {
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.moveTo(px(selectedIdx), pad.t);
      ctx.lineTo(px(selectedIdx), pad.t + plotH);
      ctx.stroke();
    }

    const strokeGrad = ctx.createLinearGradient(0, pad.t + plotH, 0, pad.t);
    if (getValueColor) {
      [0, 0.25, 0.5, 0.75, 1].forEach(stop => {
        const v = min + stop * range;
        strokeGrad.addColorStop(stop, getValueColor(v));
      });
    } else {
      strokeGrad.addColorStop(0, color);
      strokeGrad.addColorStop(1, color);
    }

    ctx.beginPath();
    vals.forEach((v: number, i: number) => i === 0 ? ctx.moveTo(px(i), py(v)) : ctx.lineTo(px(i), py(v)));
    ctx.strokeStyle = strokeGrad;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    if (selectedIdx !== null) {
      ctx.beginPath();
      ctx.arc(px(selectedIdx), py(vals[selectedIdx]), 4, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.fill();
      ctx.stroke();
    }
    
    if (labels) {
      ctx.font = '9px "Space Grotesk", sans-serif';
      ctx.fillStyle = 'rgba(240,240,255,0.35)';
      ctx.textAlign = 'center';
      labels.forEach((l: string, i: number) => {
        ctx.fillStyle = selectedIdx === i ? '#fff' : 'rgba(240,240,255,0.35)';
        ctx.fillText(l, px(i), H - 4);
      });
    }
  });

  function handleInteraction(e: MouseEvent | TouchEvent) {
    const rect = canvas.getBoundingClientRect();
    const x = ('touches' in e ? e.touches[0].clientX : e.clientX) - rect.left;
    const padL = 8;
    const padR = 8;
    const plotW = rect.width - padL - padR;
    
    const idx = Math.round(((x - padL) / plotW) * (data.length - 1));
    if (idx >= 0 && idx < data.length) {
      selectedIdx = idx;
    }
  }
</script>

<div class="relative group touch-none">
  <canvas 
    bind:this={canvas} 
    class="w-full" 
    style="height: {height}px;"
    onmousemove={handleInteraction}
    ontouchmove={handleInteraction}
    onmouseleave={() => selectedIdx = null}
  ></canvas>

  {#if selectedIdx !== null && data[selectedIdx]}
    <div class="absolute -top-6 left-1/2 -translate-x-1/2 pointer-events-none">
      <div class="bg-glass border border-white/10 rounded px-1.5 py-0.5 shadow-lg backdrop-blur-md">
        <span
          class="text-[10px] font-bold font-mono"
          style="color: {(() => {
            const raw = yKey ? data[selectedIdx]?.[yKey] : data[selectedIdx];
            const n = typeof raw === 'number' ? raw : Number(raw);
            return getValueColor && Number.isFinite(n) ? getValueColor(n) : '#fff';
          })()}"
        >
          {(() => {
            const val = yKey ? data[selectedIdx][yKey] : data[selectedIdx];
            if (formatValue) return formatValue(val);
            return typeof val === 'number' ? val.toFixed(2) : val;
          })()}{unit}
        </span>
      </div>
    </div>
  {/if}
</div>
