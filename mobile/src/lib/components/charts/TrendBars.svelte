<script lang="ts">
  const props = $props<{
    data: Array<number | null | undefined>;
    height?: number;
    min?: number;
    max?: number;
    gap?: number;
    background?: string;
    getValueColor?: (v: number) => string;
    color?: string;
    labels?: string[];
    keys?: string[];
    unit?: string;
    formatValue?: (val: number) => string;
    onSelect?: (payload: { idx: number; key?: string; value: number | null }) => void;
    showBottomLabels?: boolean;
    bottomLabelIndices?: number[];
  }>();

  let height = $derived(props.height ?? 56);
  let min = $derived(props.min ?? 0);
  let max = $derived(props.max ?? 100);
  let gap = $derived(props.gap ?? 2);
  let background = $derived(props.background ?? 'rgba(255,255,255,0.06)');
  let color = $derived(props.color ?? '#4621FF');
  let unit = $derived(props.unit ?? '');
  let showBottomLabels = $derived(props.showBottomLabels ?? false);

  const clamp01 = (n: number) => Math.max(0, Math.min(1, n));
  const clean = (v: unknown) => {
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };

  let selectedIdx = $state<number | null>(null);

  const bars = $derived.by(() => {
    const span = max - min || 1;
    return (props.data || []).map((raw: unknown) => {
      const v = clean(raw);
      if (v === null) return { v: null, h: 0, c: background };
      const h = clamp01((v - min) / span);
      const c = props.getValueColor ? props.getValueColor(v) : color;
      return { v, h, c };
    });
  });

  const selected = $derived.by(() => {
    if (selectedIdx === null) return null;
    const b = bars[selectedIdx];
    if (!b) return null;
    const label = props.labels?.[selectedIdx] ?? '';
    const valueText =
      b.v === null
        ? 'No data'
        : (props.formatValue ? props.formatValue(b.v) : String(Math.round(b.v))) + unit;
    return { idx: selectedIdx, label, valueText, color: b.c };
  });
</script>

<div
  class="w-full relative"
  style="height: {height}px;"
  role="img"
  aria-label="Trend bars"
  onmouseleave={() => (selectedIdx = null)}
>
  <div class="flex items-end w-full h-full" style="gap: {gap}px;">
    {#each bars as b, i (i)}
      <button
        type="button"
        class="flex-1 rounded-[2px] cursor-pointer border-none p-0 bg-transparent"
        style="
          height: {Math.max(2, Math.round(b.h * 100))}%;
          background: {b.c};
          opacity: {b.v === null ? 0.35 : 0.9};
          box-shadow: {b.v === null ? 'none' : '0 0 10px rgba(255,255,255,0.04)'};
        "
        aria-label={`${props.labels?.[i] ? props.labels[i] + ': ' : ''}${b.v === null ? 'No data' : (props.formatValue ? props.formatValue(b.v) : String(Math.round(b.v))) + unit}`}
        onmouseenter={() => (selectedIdx = i)}
        onfocus={() => (selectedIdx = i)}
        onclick={() => {
          const wasSelected = selectedIdx === i;
          selectedIdx = wasSelected ? null : i;
          if (props.onSelect) props.onSelect({ idx: i, key: props.keys?.[i], value: b.v });
        }}
      ></button>
    {/each}
  </div>

  {#if selected}
    <div
      class="absolute -top-7 pointer-events-none"
      style="left: {((selected.idx + 0.5) / bars.length) * 100}%; transform: translateX(-50%);"
    >
      <div class="bg-glass border border-white/10 rounded px-2 py-1 shadow-lg backdrop-blur-md whitespace-nowrap">
        <span class="text-[10px] font-mono text-text2">{selected.label}</span>
        <span class="text-[10px] font-bold font-mono ml-1" style="color: {selected.color}">
          {selected.valueText}
        </span>
      </div>
    </div>
  {/if}
</div>

{#if showBottomLabels && (props.labels?.length || 0) > 0}
  {@const n = props.labels?.length || 0}
  {@const idxs = props.bottomLabelIndices ?? [0, Math.floor((n - 1) / 2), n - 1]}
  <div class="mt-1.5 px-1 flex justify-between text-[9px] font-mono text-text2/70 select-none tracking-[0.02em]">
    <span>{props.labels?.[idxs[0]] || ''}</span>
    <span>{props.labels?.[idxs[1]] || ''}</span>
    <span>{props.labels?.[idxs[2]] || ''}</span>
  </div>
{/if}

