<script lang="ts">
  /** Weekly TSS bars (design: WTrends): completed, planned outline, recovery weeks. */
  import { format } from 'date-fns';
  import { averageCompletedTss, type WeekBucket } from './trendsWide';

  let {
    weeks,
    selected,
    onselect
  }: { weeks: WeekBucket[]; selected: number; onselect: (i: number) => void } = $props();

  const n = $derived(weeks.length);
  const max = $derived(Math.max(1, ...weeks.map((w) => Math.max(w.tss, w.planned))) * 1.06);
  const every = $derived(n > 12 ? 4 : n > 6 ? 2 : 1);
  const avg = $derived(averageCompletedTss(weeks));
  const sel = $derived(weeks[selected]);
  const lab = (d: Date) => format(d, 'd MMM').toUpperCase();
  const readout = $derived.by(() => {
    if (!sel) return '';
    if (sel.current) return `THIS WEEK · ${sel.tss}${sel.planned ? ` / ${sel.planned} PLANNED` : ' TSS SO FAR'}`;
    return `WK OF ${lab(sel.start)} · ${sel.tss} TSS${sel.recovery ? ' · RECOVERY' : ''}`;
  });
  const aria = (w: WeekBucket) =>
    `${w.current ? 'This week' : `Week of ${format(w.start, 'd MMM')}`}: ${w.tss} TSS${w.current ? ' so far' : ''}${w.planned ? `, ${w.planned} planned` : ''}${w.recovery ? ', recovery week' : ''}`;
</script>

<section aria-label="Weekly TSS" class="flex-1 min-h-0 bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex flex-col gap-3">
  <div class="flex justify-between items-baseline gap-3">
    <h2 class="m-0 font-display font-normal text-[26px]">Weekly TSS</h2>
    <span aria-live="polite" class="font-mono text-[11px] text-text1">{readout}</span>
  </div>
  <div role="group" aria-label="Weekly TSS. Select a week to inspect it." class="flex-1 min-h-[120px] flex items-end gap-1.5">
    {#each weeks as w, i (i)}
      {@const on = i === selected}
      <button
        type="button"
        aria-label={aria(w)}
        aria-pressed={on}
        class="group relative flex-1 h-full p-0 border-0 bg-transparent cursor-pointer flex flex-col justify-end"
        onclick={() => onselect(i)}
      >
        {#if w.planned > 0}
          <span aria-hidden="true" class="absolute inset-x-0 bottom-0 box-border rounded-[5px] border border-dashed border-text3" style="height: {Math.round((w.planned / max) * 100)}%"></span>
        {/if}
        <span
          aria-hidden="true"
          class="relative block w-full rounded-[5px] group-hover:brightness-[1.35] {on ? 'bg-blue' : w.recovery ? 'bg-accent-surface-border' : 'bg-popover-border'}"
          style="height: {Math.max(Math.round((w.tss / max) * 100), 2)}%"
        ></span>
      </button>
    {/each}
  </div>
  <div aria-hidden="true" class="flex gap-1.5 font-mono text-[10px] text-text2">
    {#each weeks as w, j (j)}
      <span class="flex-1 min-w-0 text-center whitespace-nowrap overflow-visible {j === selected ? 'text-text0' : ''}">{w.current ? 'NOW' : (n - 1 - j) % every === 0 ? lab(w.start) : ''}</span>
    {/each}
  </div>
  <div class="flex gap-3.5 text-[11px] text-text2">
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2 h-2 rounded-sm bg-popover-border"></span>Completed</span>
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2 h-2 box-border rounded-sm border border-dashed border-text3"></span>Planned</span>
    <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-2 h-2 rounded-sm bg-accent-surface-border"></span>Recovery week</span>
    {#if avg}<span class="ml-auto">Avg {avg} / wk</span>{/if}
  </div>
</section>
