<script lang="ts">
  /**
   * Week header for a card: ‹ [week ▾ / year] › plus a "This week" shortcut, with a month
   * calendar popover where tapping any day picks its Monday–Sunday week.
   * `value` is any `yyyy-MM-dd` inside the selected week.
   */
  import {
    addDays,
    addMonths,
    endOfMonth,
    endOfWeek,
    format,
    parse,
    startOfMonth,
    startOfWeek
  } from 'date-fns';

  let {
    value = $bindable(),
    max,
    currentLabel = 'This week',
    onchange
  }: {
    value: string;
    /** Latest selectable day (`yyyy-MM-dd`); weeks starting after it are disabled. */
    max?: string;
    currentLabel?: string;
    onchange?: (value: string) => void;
  } = $props();

  const WEEK = { weekStartsOn: 1 as const };
  const todayIso = format(new Date(), 'yyyy-MM-dd');
  const thisWeekStart = format(startOfWeek(new Date(), WEEK), 'yyyy-MM-dd');

  let open = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  let viewMonth = $state(startOfMonth(new Date()));

  const day = $derived(parse(value, 'yyyy-MM-dd', new Date()));
  const start = $derived(startOfWeek(day, WEEK));
  const end = $derived(endOfWeek(day, WEEK));
  const startIso = $derived(format(start, 'yyyy-MM-dd'));
  const isCurrent = $derived(startIso === thisWeekStart);
  const canNext = $derived(!max || format(addDays(start, 7), 'yyyy-MM-dd') <= max);

  const range = $derived(
    format(start, 'MMM') === format(end, 'MMM')
      ? `${format(start, 'd')}–${format(end, 'd MMM')}`
      : `${format(start, 'd MMM')} – ${format(end, 'd MMM')}`
  );

  const cells = $derived.by(() => {
    const first = startOfWeek(startOfMonth(viewMonth), WEEK);
    const last = endOfWeek(endOfMonth(viewMonth), WEEK);
    const out: Date[] = [];
    for (let d = first; d <= last; d = addDays(d, 1)) out.push(d);
    return out;
  });
  const rows = $derived(Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7)));

  function set(next: string) {
    if (max && format(startOfWeek(parse(next, 'yyyy-MM-dd', new Date()), WEEK), 'yyyy-MM-dd') > max) return;
    value = next;
    onchange?.(next);
  }
  function step(dir: 1 | -1) {
    if (dir === 1 && !canNext) return;
    const next = addDays(start, 7 * dir);
    // Land on the last selectable day of the week so "so far" windows stay inside max.
    const iso = format(endOfWeek(next, WEEK), 'yyyy-MM-dd');
    set(max && iso > max ? max : iso);
  }
  function toggle() {
    if (!open) viewMonth = startOfMonth(day);
    open = !open;
  }
  function pick(d: Date) {
    const iso = format(d, 'yyyy-MM-dd');
    set(max && iso > max ? max : iso);
    open = false;
  }
  function jumpToCurrent() {
    set(max && todayIso > max ? max : todayIso);
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
    <button type="button" aria-label="Previous week" class="w-10 h-10 shrink-0 rounded-xl border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={() => step(-1)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
    </button>
    <button
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label="Pick a week"
      class="flex-1 min-w-0 flex flex-col items-center gap-0.5 rounded-2xl px-3 py-1.5 bg-transparent cursor-pointer border {open ? 'border-text0' : 'border-transparent'}"
      onclick={toggle}
    >
      <span class="flex items-center gap-1.5">
        <span class="font-display text-[26px] leading-none text-text0 whitespace-nowrap">{isCurrent ? 'This week' : range}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text2 transition-transform {open ? 'rotate-180' : ''}"><path d="m6 9 6 6 6-6"></path></svg>
      </span>
      <span class="font-mono text-[11px] tracking-[0.14em] uppercase text-text2">{isCurrent ? `${range} · so far` : format(start, 'yyyy')}</span>
    </button>
    <button type="button" aria-label="Next week" disabled={!canNext} class="w-10 h-10 shrink-0 rounded-xl border-0 bg-transparent flex items-center justify-center {canNext ? 'text-text1 cursor-pointer' : 'text-text2/40 cursor-not-allowed'}" onclick={() => step(1)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    </button>
    {#if !isCurrent}
      <button type="button" class="shrink-0 h-10 px-3.5 rounded-[14px] border-0 bg-blue text-[#0B1420] text-[13px] font-semibold cursor-pointer" onclick={jumpToCurrent}>{currentLabel}</button>
    {/if}
  </div>

  {#if open}
    <div role="dialog" aria-label="Pick a week" class="absolute left-0 right-0 top-[calc(100%+8px)] z-40 rounded-[20px] border border-border bg-bg2 p-3.5 shadow-[0_16px_40px_rgba(0,0,0,0.5)]">
      <div class="mb-2 flex items-center justify-between">
        <button type="button" aria-label="Previous month" class="w-9 h-9 rounded-lg border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer" onclick={() => (viewMonth = addMonths(viewMonth, -1))}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
        </button>
        <span class="text-[15px] font-semibold">{format(viewMonth, 'MMMM yyyy')}</span>
        <button type="button" aria-label="Next month" disabled={!!max && format(addMonths(viewMonth, 1), 'yyyy-MM-dd') > max} class="w-9 h-9 rounded-lg border-0 bg-transparent flex items-center justify-center {max && format(addMonths(viewMonth, 1), 'yyyy-MM-dd') > max ? 'text-text2/40 cursor-not-allowed' : 'text-text1 cursor-pointer'}" onclick={() => (viewMonth = addMonths(viewMonth, 1))}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      </div>
      <div aria-hidden="true" class="grid grid-cols-7 pb-1 text-center font-mono text-[10px] tracking-[0.08em] text-text2">
        {#each ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as l, i (i)}<span class="py-1">{l}</span>{/each}
      </div>
      <div class="flex flex-col gap-1">
        {#each rows as row, r (r)}
          {@const rowStart = format(row[0], 'yyyy-MM-dd')}
          {@const selected = rowStart === startIso}
          {@const rowDisabled = !!max && rowStart > max}
          <div class="grid grid-cols-7 rounded-xl {selected ? 'bg-blue' : ''}">
            {#each row as d (d.toISOString())}
              {@const iso = format(d, 'yyyy-MM-dd')}
              {@const inMonth = d.getMonth() === viewMonth.getMonth()}
              <button
                type="button"
                disabled={rowDisabled}
                aria-label="Week of {format(row[0], 'd MMMM')}"
                class="h-10 rounded-xl border-0 bg-transparent text-sm font-medium {selected
                  ? 'text-[#0B1420]'
                  : rowDisabled
                    ? 'text-text2/40 cursor-not-allowed'
                    : inMonth
                      ? 'text-text0 cursor-pointer'
                      : 'text-text2/60 cursor-pointer'} {iso === todayIso && !selected ? 'underline decoration-blue underline-offset-4' : ''}"
                onclick={() => pick(d)}
              >{format(d, 'd')}</button>
            {/each}
          </div>
        {/each}
      </div>
      <div class="mt-3 flex items-center justify-between border-t border-border pt-3">
        <span class="text-xs text-text2">Pick any day to see its week</span>
        <button type="button" class="h-8 border-0 bg-transparent p-0 text-[13px] font-medium text-blue cursor-pointer" onclick={jumpToCurrent}>Jump to this week</button>
      </div>
    </div>
  {/if}
</div>
