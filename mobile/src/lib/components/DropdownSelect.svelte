<script module lang="ts">
  export type SelectOption = { value: string; label: string };
</script>

<script lang="ts">
  let {
    id,
    value = $bindable(),
    options = [],
    disabled = false,
    ariaLabel,
    buttonClass = '',
    popoverClass = '',
    align = 'left',
  }: {
    id?: string;
    value: string;
    options?: SelectOption[];
    disabled?: boolean;
    ariaLabel?: string;
    buttonClass?: string;
    popoverClass?: string;
    align?: 'left' | 'right';
  } = $props();

  let open = $state(false);
  let anchorEl = $state<HTMLElement | null>(null);
  let popoverEl = $state<HTMLElement | null>(null);

  const selected = $derived.by(() => options.find((o) => String(o.value) === String(value)) ?? null);
  const label = $derived(selected?.label ?? 'Select');

  const baseButton =
    'w-full flex items-center justify-between gap-2 bg-glass2 border border-border rounded-lg text-text0 outline-none focus:border-blue disabled:opacity-50';

  function toggle() {
    if (disabled) return;
    open = !open;
  }

  function close() {
    open = false;
  }

  function selectOpt(opt: SelectOption) {
    value = opt.value;
    close();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
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
</script>

<div class="relative inline-block w-full">
  <button
    bind:this={anchorEl}
    id={id}
    type="button"
    class={baseButton + ' ' + (buttonClass || 'p-2.5 text-sm')}
    aria-label={ariaLabel}
    aria-haspopup="listbox"
    aria-expanded={open}
    disabled={disabled}
    onclick={toggle}
    onkeydown={onKeydown}
  >
    <span class="truncate">{label}</span>
    <span class="opacity-70 shrink-0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </span>
  </button>

  {#if open}
    <div
      bind:this={popoverEl}
      class={[
        'absolute top-[calc(100%+8px)] min-w-full rounded-xl border border-border bg-[rgba(15,15,20,0.92)] backdrop-blur-xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] p-1 z-50',
        align === 'right' ? 'right-0' : 'left-0',
        popoverClass
      ].join(' ')}
      role="listbox"
      aria-label={ariaLabel ?? 'Select'}
    >
      {#each options as opt (opt.value)}
        {@const active = String(opt.value) === String(value)}
        <button
          type="button"
          class={[
            'w-full text-left px-2.5 py-2 rounded-lg text-[12px] font-mono transition-colors',
            active ? 'bg-blue text-white' : 'hover:bg-glass2 text-text0'
          ].join(' ')}
          onclick={() => selectOpt(opt)}
        >
          {opt.label}
        </button>
      {/each}
    </div>
  {/if}
</div>

