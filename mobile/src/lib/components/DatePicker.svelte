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
    ariaLabel
  }: {
    id?: string;
    value: string; // YYYY-MM-DD
    max?: string; // YYYY-MM-DD
    disabled?: boolean;
    placeholder?: string;
    buttonClass?: string;
    popoverClass?: string;
    ariaLabel?: string;
  } = $props();

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
    <span class={selectedDate ? 'truncate' : 'truncate opacity-60'}>{displayLabel}</span>
    <span class="opacity-70 shrink-0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </span>
  </button>

  {#if open}
    <div
      bind:this={popoverEl}
      class={
        'absolute left-0 top-[calc(100%+8px)] w-[270px] rounded-xl border border-border bg-[rgba(15,15,20,0.92)] backdrop-blur-xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] p-3 z-50 ' +
        popoverClass
      }
      role="dialog"
      aria-label="Calendar"
    >
      <div class="flex items-center justify-between mb-2">
        <button
          type="button"
          class="w-8 h-8 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors"
          aria-label={yearMode ? 'Previous year' : 'Previous month'}
          onclick={() => (viewMonth = yearMode ? subMonths(viewMonth, 12) : subMonths(viewMonth, 1))}
        >
          ‹
        </button>

        <button
          type="button"
          class="text-[12px] font-semibold text-text0 font-mono px-2 py-1 rounded-lg hover:bg-glass2 transition-colors"
          aria-label="Select year"
          onclick={() => (yearMode = !yearMode)}
        >
          {format(viewMonth, yearMode ? 'yyyy' : 'MMM yyyy')}
        </button>

        <button
          type="button"
          class="w-8 h-8 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors"
          aria-label={yearMode ? 'Next year' : 'Next month'}
          onclick={() => (viewMonth = yearMode ? addMonths(viewMonth, 12) : addMonths(viewMonth, 1))}
        >
          ›
        </button>
      </div>

      {#if yearMode}
        <div class="max-h-[240px] overflow-auto rounded-lg border border-border/50 bg-glass2/30 p-1">
          {#each years as y (y)}
            <button
              type="button"
              class={[
                'w-full text-left px-2.5 py-2 rounded-lg text-[12px] font-mono transition-colors',
                y === viewMonth.getFullYear() ? 'bg-blue text-white' : 'hover:bg-glass2 text-text0'
              ].join(' ')}
              onclick={() => setYear(y)}
            >
              {y}
            </button>
          {/each}
        </div>
      {:else}
        <div class="grid grid-cols-7 gap-1 mb-1.5">
          {#each dow as d, i (i)}
            <div class="text-[10px] text-text2 font-mono text-center py-1">{d}</div>
          {/each}
        </div>

        <div class="grid grid-cols-7 gap-1">
          {#each days as d (d.toISOString())}
            {@const inMonth = isSameMonth(d, viewMonth)}
            {@const isSelected = selectedDate ? isSameDay(d, selectedDate) : false}
            {@const isDisabled = !canPick(d)}
            <button
              type="button"
              class={[
                'h-8 rounded-lg text-[12px] font-mono transition-colors',
                inMonth ? 'text-text0' : 'text-text2/60',
                isDisabled ? 'opacity-35 cursor-not-allowed' : 'hover:bg-glass2',
                isSelected ? 'bg-blue text-white hover:bg-blue' : 'bg-transparent'
              ].join(' ')}
              disabled={isDisabled}
              aria-label={format(d, 'yyyy-MM-dd')}
              onclick={() => setDate(d)}
            >
              {format(d, 'd')}
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

