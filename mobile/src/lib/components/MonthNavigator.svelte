<script lang="ts">
  /**
   * Month header for a card: ‹ [Month ▾ / year] › plus a "This month" shortcut, with a
   * year + 12-month grid popover. `value` is `yyyy-MM`.
   */
  import { addMonths, format, parse } from 'date-fns';

  let {
    value = $bindable(),
    max,
    subtitle = '',
    currentLabel = 'This month',
    onchange
  }: {
    value: string;
    /** Latest selectable month (`yyyy-MM`); later months are disabled. */
    max?: string;
    /** Shown under the month name for the current month (e.g. "This month · so far"). */
    subtitle?: string;
    currentLabel?: string;
    onchange?: (value: string) => void;
  } = $props();

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const currentKey = format(new Date(), 'yyyy-MM');

  let open = $state(false);
  let rootEl = $state<HTMLElement | null>(null);

  const date = $derived(parse(`${value}-01`, 'yyyy-MM-dd', new Date()));
  const isCurrent = $derived(value === currentKey);
  const canNext = $derived(!max || format(addMonths(date, 1), 'yyyy-MM') <= max);
  let viewYear = $state(new Date().getFullYear());

  function set(next: string) {
    if (max && next > max) return;
    value = next;
    onchange?.(next);
  }
  function step(dir: 1 | -1) {
    if (dir === 1 && !canNext) return;
    set(format(addMonths(date, dir), 'yyyy-MM'));
  }
  function toggle() {
    if (!open) viewYear = date.getFullYear();
    open = !open;
  }
  function pick(monthIdx: number) {
    set(`${viewYear}-${String(monthIdx + 1).padStart(2, '0')}`);
    open = false;
  }
  function jumpToCurrent() {
    set(currentKey);
    open = false;
  }

  $effect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) open = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') open = false;
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  });
</script>

<div class="relative" bind:this={rootEl}>
  <div class="flex items-center gap-2">
    <button type="button" aria-label="Previous month" class="w-10 h-10 shrink-0 rounded-xl border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={() => step(-1)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
    </button>
    <button
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label="Pick a month"
      class="flex-1 min-w-0 flex flex-col items-center gap-0.5 rounded-2xl px-3 py-1.5 bg-transparent cursor-pointer border {open ? 'border-text0' : 'border-transparent'}"
      onclick={toggle}
    >
      <span class="flex items-center gap-1.5">
        <span class="font-display text-[26px] leading-none text-text0">{format(date, 'MMMM')}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text2 transition-transform {open ? 'rotate-180' : ''}"><path d="m6 9 6 6 6-6"></path></svg>
      </span>
      <span class="font-mono text-[11px] tracking-[0.14em] uppercase {isCurrent && subtitle ? 'text-text2' : 'text-text2'}">{isCurrent && subtitle ? subtitle : format(date, 'yyyy')}</span>
    </button>
    <button type="button" aria-label="Next month" disabled={!canNext} class="w-10 h-10 shrink-0 rounded-xl border-0 bg-transparent flex items-center justify-center {canNext ? 'text-text1 cursor-pointer' : 'text-text2/40 cursor-not-allowed'}" onclick={() => step(1)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    </button>
    {#if !isCurrent}
      <button type="button" class="shrink-0 h-10 px-3.5 rounded-[14px] border-0 bg-blue text-[#0B1420] text-[13px] font-semibold cursor-pointer" onclick={jumpToCurrent}>{currentLabel}</button>
    {/if}
  </div>

  {#if open}
    <div role="dialog" aria-label="Pick a month" class="absolute left-0 right-0 top-[calc(100%+8px)] z-40 rounded-[20px] border border-border bg-bg2 p-3.5 shadow-[0_16px_40px_rgba(0,0,0,0.5)]">
      <div class="mb-3 flex items-center justify-between">
        <button type="button" aria-label="Previous year" class="w-9 h-9 rounded-lg border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={() => (viewYear -= 1)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
        </button>
        <span class="text-[15px] font-semibold">{viewYear}</span>
        <button type="button" aria-label="Next year" disabled={!!max && `${viewYear + 1}-01` > max} class="w-9 h-9 rounded-lg border-0 bg-transparent flex items-center justify-center {max && `${viewYear + 1}-01` > max ? 'text-text2/40 cursor-not-allowed' : 'text-text1 cursor-pointer'}" onclick={() => (viewYear += 1)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      </div>
      <div class="grid grid-cols-3 gap-2">
        {#each MONTHS as m, i (m)}
          {@const key = `${viewYear}-${String(i + 1).padStart(2, '0')}`}
          {@const disabled = !!max && key > max}
          <button
            type="button"
            {disabled}
            aria-pressed={key === value}
            class="h-11 rounded-xl text-sm font-medium border {key === value
              ? 'bg-blue text-[#0B1420] border-blue'
              : key === currentKey
                ? 'bg-bg1 text-text0 border-blue/70'
                : disabled
                  ? 'bg-bg1 text-text2/40 border-border cursor-not-allowed'
                  : 'bg-bg1 text-text0 border-border cursor-pointer'}"
            onclick={() => pick(i)}
          >{m}</button>
        {/each}
      </div>
      <div class="mt-3 flex items-center justify-between border-t border-border pt-3">
        <span class="text-xs text-text2">Pick a month</span>
        <button type="button" class="h-8 border-0 bg-transparent p-0 text-[13px] font-medium text-blue cursor-pointer" onclick={jumpToCurrent}>Jump to this month</button>
      </div>
    </div>
  {/if}
</div>
