<script lang="ts">
  let {
    label,
    value,
    unit,
    color = 'var(--teal)',
    sub,
    labelClass,
    subClass,
    /** When set, skips inline color and uses Tailwind classes for the headline value only */
    valueClassName,
  } = $props<{
    label: string;
    value: number | string;
    unit?: string;
    color?: string;
    sub?: string;
    /** Full class string for label (defaults to muted design tokens) */
    labelClass?: string;
    subClass?: string;
    valueClassName?: string;
  }>();
</script>

<div class="flex flex-col gap-0.5 leading-tight">
  <span class={labelClass ?? 'text-[10px] text-text2 uppercase tracking-[0.08em] font-mono'}>{label}</span>
  <span
    class="text-[22px] font-semibold tabular-nums leading-none tracking-[-0.02em] {valueClassName ?? ''}"
    style:color={valueClassName ? undefined : color}
  >
    {value}
    {#if unit}
      <span class="text-[12px] font-normal ml-0.5 opacity-90">{unit}</span>
    {/if}
  </span>
  {#if sub}
    <span class={subClass ?? 'text-[10px] text-text2'}>{sub}</span>
  {/if}
</div>
