<script lang="ts">
  import {
    addDays,
    addMonths,
    endOfMonth,
    endOfWeek,
    format,
    isAfter,
    isSameDay,
    isSameMonth,
    parseISO,
    startOfMonth,
    startOfWeek,
    subMonths
  } from 'date-fns';

  let {
    id,
    value = $bindable(),
    max,
    disabled = false,
    placeholder = 'Select date',
    buttonClass = '',
    popoverClass = '',
    ariaLabel,
    label = '',
    hideChevron = false,
    marked = []
  }: {
    id?: string;
    value: string; // YYYY-MM-DD
    max?: string; // YYYY-MM-DD
    disabled?: boolean;
    placeholder?: string;
    buttonClass?: string;
    popoverClass?: string;
    ariaLabel?: string;
    /** Replaces the formatted date in the trigger (e.g. "Today"); also swaps the chevron for a calendar icon. */
    label?: string;
    hideChevron?: boolean;
    /** Days (yyyy-MM-dd) that have data; shown with a dot and a "Has data" legend. */
    marked?: string[];
  } = $props();

  const todayIso = format(new Date(), 'yyyy-MM-dd');
  const markedSet = $derived(new Set(marked));

  let open = $state(false);
  let anchorEl = $state<HTMLElement | null>(null);
  let popoverEl = $state<HTMLElement | null>(null);

  const selectedDate = $derived.by(() => {
    if (!value) return null;
    const d = new Date(value + 'T00:00:00');
    return Number.isNaN(d.getTime()) ? null : d;
  });

  const maxDate = $derived.by(() => {
    if (!max) return null;
    const d = new Date(max + 'T00:00:00');
    return Number.isNaN(d.getTime()) ? null : d;
  });

  let viewMonth = $state<Date>(new Date());

  $effect(() => {
    // Keep the view aligned with selection when closed (avoid jump while open).
    if (open) return;
    if (selectedDate) viewMonth = selectedDate;
  });

  const gridStart = $derived(startOfWeek(startOfMonth(viewMonth), { weekStartsOn: 1 }));
  const gridEnd = $derived(endOfWeek(endOfMonth(viewMonth), { weekStartsOn: 1 }));
  const days = $derived.by(() => {
    const out: Date[] = [];
    for (let d = gridStart; d <= gridEnd; d = addDays(d, 1)) out.push(d);
    return out;
  });

  const canPick = (d: Date) => {
    if (disabled) return false;
    if (maxDate && isAfter(d, maxDate)) return false;
    return true;
  };

  function setDate(d: Date) {
    if (!canPick(d)) return;
    value = format(d, 'yyyy-MM-dd');
    open = false;
  }

  function toggle() {
    if (disabled) return;
    open = !open;
    if (open) viewMonth = selectedDate ?? new Date();
  }

  function close() {
    open = false;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  }

  $effect(() => {
    if (!open) return;

    const onDocPointerDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (anchorEl?.contains(t)) return;
      if (popoverEl?.contains(t)) return;
      close();
    };

    const onDocKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };

    document.addEventListener('pointerdown', onDocPointerDown, { capture: true });
    document.addEventListener('keydown', onDocKey, { capture: true });
    return () => {
      document.removeEventListener('pointerdown', onDocPointerDown, { capture: true } as any);
      document.removeEventListener('keydown', onDocKey, { capture: true } as any);
    };
  });

  const baseButton =
    'w-full flex items-center justify-between gap-2 bg-glass2 border border-border rounded-lg text-text0 outline-none focus:border-blue disabled:opacity-50';

  const displayLabel = $derived(
    selectedDate ? format(selectedDate, 'MMM d, yyyy') : placeholder
  );

  const dow = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];



  let yearMode = $state(false);

  const nextDisabled = $derived(
    !!maxDate &&
      (yearMode
        ? viewMonth.getFullYear() + 1 > maxDate.getFullYear()
        : startOfMonth(addMonths(viewMonth, 1)) > maxDate)
  );

  const yearMin = 1900;
  const yearMax = $derived((maxDate ?? new Date()).getFullYear());
  const years = $derived.by(() => {
    const ys: number[] = [];
    for (let y = yearMax; y >= yearMin; y--) ys.push(y);
    return ys;
  });

  function setYear(y: number) {
    // Preserve month when switching years.
    const m = viewMonth.getMonth();
    viewMonth = new Date(y, m, 1);
    yearMode = false;
  }
</script>

<div class="relative inline-block w-full">
  <button
    bind:this={anchorEl}
    id={id}
    type="button"
    class={baseButton + ' ' + (buttonClass || 'px-2 py-1 pr-2 text-[12px]')}
    aria-label={ariaLabel}
    aria-haspopup="dialog"
    aria-expanded={open}
    disabled={disabled}
    onclick={toggle}
    onkeydown={onKeydown}
  >
    {#if hideChevron}
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0 opacity-80"><rect x="3" y="5" width="18" height="16" rx="3"></rect><path d="M3 10h18M8 3v4M16 3v4"></path></svg>
    {/if}
    <span class={selectedDate ? 'truncate' : 'truncate opacity-60'}>{label || displayLabel}</span>
    {#if !hideChevron}
    <span class="opacity-70 shrink-0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </span>
    {/if}
  </button>

  {#if open}
    <div
      bind:this={popoverEl}
      class={
        'absolute left-0 top-[calc(100%+8px)] w-[300px] max-w-[calc(100vw-32px)] rounded-[20px] border border-border bg-bg2 shadow-[0_16px_40px_rgba(0,0,0,0.5)] p-3.5 z-50 ' +
        popoverClass
      }
      role="dialog"
      aria-label="Calendar"
    >
      <div class="flex items-center justify-between mb-2">
        <button
          type="button"
          class="w-9 h-9 rounded-lg border-0 bg-transparent text-text1 flex items-center justify-center cursor-pointer"
          aria-label={yearMode ? 'Previous year' : 'Previous month'}
          onclick={() => (viewMonth = yearMode ? subMonths(viewMonth, 12) : subMonths(viewMonth, 1))}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
        </button>

        <button
          type="button"
          class="h-9 px-2 rounded-lg border-0 bg-transparent text-[15px] font-semibold text-text0 cursor-pointer"
          aria-label="Select year"
          onclick={() => (yearMode = !yearMode)}
        >
          {format(viewMonth, yearMode ? 'yyyy' : 'MMMM yyyy')}
        </button>

        <button
          type="button"
          class="w-9 h-9 rounded-lg border-0 bg-transparent flex items-center justify-center {nextDisabled ? 'text-text2/40 cursor-not-allowed' : 'text-text1 cursor-pointer'}"
          aria-label={yearMode ? 'Next year' : 'Next month'}
          disabled={nextDisabled}
          onclick={() => (viewMonth = yearMode ? addMonths(viewMonth, 12) : addMonths(viewMonth, 1))}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      </div>

      {#if yearMode}
        <div class="max-h-[240px] overflow-auto grid grid-cols-3 gap-2">
          {#each years as y (y)}
            <button
              type="button"
              class="h-11 rounded-xl border text-sm font-medium cursor-pointer {y === viewMonth.getFullYear() ? 'bg-blue text-[#0B1420] border-blue' : 'bg-bg1 text-text0 border-border'}"
              onclick={() => setYear(y)}
            >
              {y}
            </button>
          {/each}
        </div>
      {:else}
        <div class="grid grid-cols-7 pb-1">
          {#each dow as d, i (i)}
            <div class="text-[10px] text-text2 font-mono tracking-[0.08em] text-center py-1">{d}</div>
          {/each}
        </div>

        <div class="grid grid-cols-7 gap-1">
          {#each days as d (d.toISOString())}
            {@const iso = format(d, 'yyyy-MM-dd')}
            {@const inMonth = isSameMonth(d, viewMonth)}
            {@const isSelected = selectedDate ? isSameDay(d, selectedDate) : false}
            {@const isToday = iso === todayIso}
            {@const isDisabled = !canPick(d)}
            <button
              type="button"
              class="relative h-10 rounded-xl text-sm font-medium border {isSelected
                ? 'bg-blue text-[#0B1420] border-blue font-semibold'
                : isToday
                  ? 'bg-transparent border-blue/70 text-text0'
                  : 'bg-transparent border-transparent'} {isSelected
                ? ''
                : isDisabled
                  ? 'text-text2/30 cursor-not-allowed'
                  : inMonth
                    ? 'text-text0 cursor-pointer'
                    : 'text-text2/60 cursor-pointer'}"
              disabled={isDisabled}
              aria-label={format(d, 'EEEE d MMMM yyyy')}
              aria-pressed={isSelected}
              onclick={() => setDate(d)}
            >
              {format(d, 'd')}
              {#if markedSet.has(iso)}
                <span aria-hidden="true" class="absolute left-1/2 bottom-1 h-1 w-1 -translate-x-1/2 rounded-full {isSelected ? 'bg-[#0B1420]' : 'bg-text2'}"></span>
              {/if}
            </button>
          {/each}
        </div>
      {/if}

      <div class="mt-3 flex items-center justify-between border-t border-border pt-3">
        {#if marked.length > 0}
          <span class="flex items-center gap-1.5 text-xs text-text2"><span aria-hidden="true" class="h-1.5 w-1.5 rounded-full bg-text2"></span>Has data</span>
        {:else}
          <span class="text-xs text-text2">Pick a day</span>
        {/if}
        <button
          type="button"
          class="h-8 border-0 bg-transparent p-0 text-[13px] font-medium text-blue cursor-pointer disabled:opacity-40"
          disabled={!canPick(new Date())}
          onclick={() => setDate(new Date())}
        >Jump to today</button>
      </div>
    </div>
  {/if}
</div>
