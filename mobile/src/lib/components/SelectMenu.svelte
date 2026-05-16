<script module lang="ts">
  export type SelectOption = { value: string; label: string };
</script>

<script lang="ts">
  let {
    id,
    value = $bindable(),
    options = [],
    disabled = false,
    placeholder = 'Select',
    buttonClass = '',
    popoverClass = '',
    ariaLabel
  }: {
    id?: string;
    value: string;
    options: SelectOption[];
    disabled?: boolean;
    placeholder?: string;
    buttonClass?: string;
    popoverClass?: string;
    ariaLabel?: string;
  } = $props();

  let open = $state(false);
  let anchorEl = $state<HTMLElement | null>(null);
  let popoverEl = $state<HTMLElement | null>(null);
  let activeIndex = $state<number>(-1);

  const selectedLabel = $derived.by(() => {
    const m = options.find((o) => o.value === value);
    return m?.label ?? '';
  });

  function toggle() {
    if (disabled) return;
    open = !open;
    if (open) {
      activeIndex = Math.max(0, options.findIndex((o) => o.value === value));
    }
  }

  function close() {
    open = false;
  }

  function selectAt(idx: number) {
    const opt = options[idx];
    if (!opt) return;
    value = opt.value;
    close();
  }

  function onButtonKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
    if ((e.key === 'Enter' || e.key === ' ') && !open) {
      e.preventDefault();
      toggle();
    }
  }

  function onListKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = Math.min(options.length - 1, Math.max(0, activeIndex) + 1);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = Math.max(0, Math.max(0, activeIndex) - 1);
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0) selectAt(activeIndex);
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
</script>

<div class="relative inline-block w-full">
  <button
    bind:this={anchorEl}
    id={id}
    type="button"
    class={baseButton + ' ' + (buttonClass || 'p-2.5 pr-2 text-sm')}
    aria-label={ariaLabel}
    aria-haspopup="listbox"
    aria-expanded={open}
    disabled={disabled}
    onclick={toggle}
    onkeydown={onButtonKey}
  >
    <span class={selectedLabel ? 'truncate' : 'truncate opacity-60'}>
      {selectedLabel || placeholder}
    </span>
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
        'absolute left-0 top-[calc(100%+8px)] w-full rounded-xl border border-border bg-[rgba(15,15,20,0.92)] backdrop-blur-xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] p-1.5 z-50 max-h-64 overflow-auto ' +
        popoverClass
      }
      role="listbox"
      tabindex="0"
      onkeydown={onListKey}
    >
    {#each options as opt, i (opt.value)}
      <button
        type="button"
        role="option"
        aria-selected={opt.value === value}
        class={[
          'w-full text-left px-2.5 py-2 rounded-lg text-[12px] transition-colors',
          i === activeIndex ? 'bg-glass2' : 'bg-transparent hover:bg-glass2',
          opt.value === value ? 'text-text0 font-semibold' : 'text-text1'
        ].join(' ')}
        onclick={() => selectAt(i)}
        onmouseenter={() => (activeIndex = i)}
      >
        {opt.label}
      </button>
    {/each}
    </div>
  {/if}
</div>

