<script lang="ts">
  import type { ActivityStreams } from '$lib/services/activityService';

  /**
   * Primary effort line (power, else speed) over heart rate, each scaled to its own range
   * so the shapes can be compared, as in the workout detail design.
   */
  let { streams, durationLabel = '' }: { streams: ActivityStreams; durationLabel?: string } = $props();

  const W = 314;
  const H = 110;
  const POINTS = 140;

  function series(values: number[] | undefined): number[] | null {
    if (!values || values.length < 2) return null;
    const clean = values.map((v) => (Number.isFinite(v) ? Number(v) : 0));
    return clean.some((v) => v > 0) ? clean : null;
  }

  /** Bucket-average down to POINTS samples, then a light 3-point smooth. */
  function downsample(values: number[]): number[] {
    const out: number[] = [];
    const size = values.length / POINTS;
    for (let i = 0; i < POINTS; i++) {
      const a = Math.floor(i * size);
      const b = Math.max(a + 1, Math.floor((i + 1) * size));
      let sum = 0;
      for (let j = a; j < b && j < values.length; j++) sum += values[j];
      out.push(sum / (Math.min(b, values.length) - a));
    }
    return out.map((v, i) => (out[i - 1] !== undefined && out[i + 1] !== undefined ? (out[i - 1] + v + out[i + 1]) / 3 : v));
  }

  function path(values: number[]): string {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = Math.max(hi - lo, 1e-9);
    return values
      .map((v, i) => `${i === 0 ? 'M' : 'L'}${((i / (values.length - 1)) * W).toFixed(1)},${(8 + (1 - (v - lo) / span) * (H - 16)).toFixed(1)}`)
      .join(' ');
  }

  const ts = $derived(streams?.time_series ?? {});
  const power = $derived(series(ts.watts));
  const speed = $derived(power ? null : series(ts.velocity_smooth));
  const hr = $derived(series(ts.heartrate));
  const effort = $derived(power ?? speed);
  const effortLabel = $derived(power ? 'Power' : 'Speed');

  const effortPath = $derived(effort ? path(downsample(effort)) : null);
  const hrPath = $derived(hr ? path(downsample(hr)) : null);
</script>

{#if effortPath || hrPath}
  <section aria-label="{effortLabel} and heart rate" class="bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-2.5">
    <div class="flex justify-between items-baseline">
      <h2 class="m-0 font-display font-normal text-[22px]">{effort ? effortLabel : 'Heart rate'}{effort && hr ? ' & heart rate' : ''}</h2>
      {#if durationLabel}<span class="font-mono text-[11px] text-text2">{durationLabel}</span>{/if}
    </div>
    <svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{effortLabel} and heart rate over the workout" class="block">
      {#each [27, 55, 83] as gy (gy)}<line x1="0" y1={gy} x2={W} y2={gy} stroke="var(--bg3)" stroke-width="1"></line>{/each}
      {#if effortPath}<path d={effortPath} fill="none" stroke="var(--blue)" stroke-width="1.6" stroke-linejoin="round"></path>{/if}
      {#if hrPath}<path d={hrPath} fill="none" stroke="var(--red)" stroke-width="1.3" stroke-opacity="0.85" stroke-linejoin="round"></path>{/if}
    </svg>
    <div class="flex gap-4 text-[11px] text-text2">
      {#if effortPath}<span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 bg-blue"></span>{effortLabel}</span>{/if}
      {#if hrPath}<span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 bg-red"></span>Heart rate</span>{/if}
    </div>
  </section>
{/if}
