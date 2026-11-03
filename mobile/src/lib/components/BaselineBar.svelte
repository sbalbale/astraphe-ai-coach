<script lang="ts">
  /**
   * One "vs your baseline" row: a track with the baseline tick in the middle and a dot
   * placed by the z-score (±2 at the ends), coloured by how good or bad the deviation is.
   * Used on the phone Recovery page and the wide Body view.
   */
  let {
    name,
    value,
    delta,
    z,
    color,
    labelWidth = 84,
    valueWidth = 72,
    size = 'sm'
  }: {
    name: string;
    value: string;
    delta: string;
    /** Position: standard deviations from baseline; null centres the dot. */
    z: number | null;
    /** Dot and delta colour (CSS colour or var). */
    color: string;
    labelWidth?: number;
    valueWidth?: number;
    size?: 'sm' | 'lg';
  } = $props();

  const pos = $derived(z === null ? 50 : 50 + Math.max(-2, Math.min(2, z)) * 25);
</script>

<div
  class="grid gap-3 items-center border-t border-border {size === 'lg' ? 'py-3.5' : 'py-2'}"
  style="grid-template-columns: {labelWidth}px 1fr {valueWidth}px"
>
  <span class="{size === 'lg' ? 'text-[14px]' : 'text-[13px]'} text-text1">{name}</span>
  <div aria-hidden="true" class="relative h-1.5 rounded-[3px] bg-border">
    <span class="absolute left-1/2 -top-1 w-px h-3.5 bg-text2/50"></span>
    <span class="absolute -top-[3px] w-3 h-3 rounded-full -translate-x-1/2" style="left: {pos}%; background: {color}"></span>
  </div>
  <span class="text-right flex flex-col gap-px">
    <span class="font-mono {size === 'lg' ? 'text-[15px]' : 'text-[13px]'}">{value}</span>
    <span class="{size === 'lg' ? 'text-[12px]' : 'text-[11px]'}" style="color: {color}">{delta}</span>
  </span>
</div>
