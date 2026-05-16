<script lang="ts">
  import { addMonths, format, isAfter, parse, parseISO, startOfMonth, subMonths } from 'date-fns';

  let {
    id,
    value = $bindable(),
    max,
    disabled = false,
    placeholder = 'Select month',
    buttonClass = '',
    popoverClass = '',
    ariaLabel
  }: {
    id?: string;
    value: string; // YYYY-MM
    max?: string; // YYYY-MM
    disabled?: boolean;
    placeholder?: string;
    buttonClass?: string;
    popoverClass?: string;
    ariaLabel?: string;
  } = $props();

  let open = $state(false);
  let anchorEl = $state<HTMLElement | null>(null);
  let popoverEl = $state<HTMLElement | null>(null);

  const selectedMonth = $derived.by(() => {
    if (!value) return null;
    // Parse YYYY-MM into a Date at first day
    const d = parse(value + '-01', 'yyyy-MM-dd', new Date());
    return Number.isNaN(d.getTime()) ? null : d;
  });

  const maxMonth = $derived.by(() => {
    if (!max) return null;
    const d = parse(max + '-01', 'yyyy-MM-dd', new Date());
    return Number.isNaN(d.getTime()) ? null : d;
  });

  let viewYear = $state<number>(new Date().getFullYear());

  $effect(() => {
    if (open) return;
    if (selectedMonth) viewYear = selectedMonth.getFullYear();
  });

  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec'
  ];

  function monthDate(year: number, idx: number) {
    return startOfMonth(new Date(year, idx, 1));
  }

  function canPick(d: Date) {
    if (disabled) return false;
    if (maxMonth && isAfter(d, maxMonth)) return false;
    return true;
  }

  function setMonth(d: Date) {
    if (!canPick(d)) return;
    value = format(d, 'yyyy-MM');
    open = false;
  }

  function toggle() {
    if (disabled) return;
    open = !open;
    if (open) viewYear = (selectedMonth ?? new Date()).getFullYear();
  }

  function close() {
    open = false;
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

  const displayLabel = $derived(selectedMonth ? format(selectedMonth, 'MMM yyyy') : placeholder);
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
  >
    <span class={selectedMonth ? 'truncate' : 'truncate opacity-60'}>{displayLabel}</span>
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
      aria-label="Month picker"
    >
    <div class="flex items-center justify-between mb-2">
      <button
        type="button"
        class="w-8 h-8 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors"
        aria-label="Previous year"
        onclick={() => (viewYear = viewYear - 1)}
      >
        ‹
      </button>
      <div class="text-[12px] font-semibold text-text0 font-mono">{viewYear}</div>
      <button
        type="button"
        class="w-8 h-8 rounded-lg bg-glass2 border border-border/50 hover:bg-glass transition-colors"
        aria-label="Next year"
        onclick={() => (viewYear = viewYear + 1)}
      >
        ›
      </button>
    </div>

    <div class="grid grid-cols-3 gap-2">
      {#each months as m, idx (m)}
        {@const d = monthDate(viewYear, idx)}
        {@const isSelected =
          selectedMonth ? selectedMonth.getFullYear() === viewYear && selectedMonth.getMonth() === idx : false}
        {@const isDisabled = !canPick(d)}
        <button
          type="button"
          class={[
            'h-9 rounded-lg text-[12px] font-mono transition-colors',
            isDisabled ? 'opacity-35 cursor-not-allowed' : 'hover:bg-glass2',
            isSelected ? 'bg-blue text-white hover:bg-blue' : 'bg-transparent text-text0'
          ].join(' ')}
          disabled={isDisabled}
          onclick={() => setMonth(d)}
        >
          {m}
        </button>
      {/each}
    </div>
    </div>
  {/if}
</div>

