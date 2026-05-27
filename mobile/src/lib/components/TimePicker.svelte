<script lang="ts">
  let {
    id,
    value = $bindable(),
    disabled = false,
    ariaLabel,
    minuteStep = 1,
    buttonClass = '',
    popoverClass = '',
  }: {
    id?: string;
    value: string; // HH:MM
    disabled?: boolean;
    ariaLabel?: string;
    minuteStep?: number;
    buttonClass?: string;
    popoverClass?: string;
  } = $props();

  let open = $state(false);
  let anchorEl = $state<HTMLElement | null>(null);
  let popoverEl = $state<HTMLElement | null>(null);
  let hAlign = $state<'left' | 'right'>('left');
  let vAlign = $state<'down' | 'up'>('down');

  const baseButton =
    'w-full flex items-center justify-between gap-2 bg-glass2 border border-border rounded-lg text-text0 outline-none focus:border-blue disabled:opacity-50';

  function toggle() {
    if (disabled) return;
    open = !open;
  }

  function close() {
    open = false;
  }

  function computePlacement() {
    const a = anchorEl;
    if (!a) return;
    const r = a.getBoundingClientRect();
    const popW = 210;
    const popH = 280;
    const vw = window.innerWidth || 0;
    const vh = window.innerHeight || 0;

    // Prefer opening down+left, but flip if clipped.
    const wouldClipRight = r.left + popW > vw - 8;
    const wouldClipBottom = r.bottom + 8 + popH > vh - 8;
    hAlign = wouldClipRight ? 'right' : 'left';
    vAlign = wouldClipBottom ? 'up' : 'down';
  }

  function clampStep(step: number) {
    const s = Math.floor(Number(step) || 1);
    return Math.min(30, Math.max(1, s));
  }

  const step = $derived(clampStep(minuteStep));

  const parts = $derived.by(() => {
    const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(String(value || '').trim());
    if (!m) return { hh: '08', mm: '00' };
    return { hh: m[1], mm: m[2] };
  });

  const hours = $derived(Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')));
  const minutes = $derived.by(() => {
    const out: string[] = [];
    for (let i = 0; i < 60; i += step) out.push(String(i).padStart(2, '0'));
    return out;
  });

  function setHour(hh: string) {
    value = `${hh}:${parts.mm}`;
  }

  function setMinute(mm: string) {
    value = `${parts.hh}:${mm}`;
    close();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  }

  $effect(() => {
    if (!open) return;
    computePlacement();
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
    const onResize = () => computePlacement();
    // Capture scroll from any container; modal sheets often scroll.
    const onScroll = () => computePlacement();
    document.addEventListener('pointerdown', onDocPointerDown, { capture: true });
    document.addEventListener('keydown', onDocKey, { capture: true });
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, { capture: true } as any);
    return () => {
      document.removeEventListener('pointerdown', onDocPointerDown, { capture: true } as any);
      document.removeEventListener('keydown', onDocKey, { capture: true } as any);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onScroll, { capture: true } as any);
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
    aria-haspopup="dialog"
    aria-expanded={open}
    disabled={disabled}
    onclick={toggle}
    onkeydown={onKeydown}
  >
    <span class="truncate font-mono tabular-nums">{parts.hh}:{parts.mm}</span>
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
        'absolute w-[210px] rounded-xl border border-border bg-[rgba(15,15,20,0.92)] backdrop-blur-xl shadow-[0_10px_30px_rgba(0,0,0,0.35)] p-2 z-50',
        vAlign === 'up' ? 'bottom-[calc(100%+8px)]' : 'top-[calc(100%+8px)]',
        hAlign === 'right' ? 'right-0' : 'left-0',
        popoverClass
      ].join(' ')}
      role="dialog"
      aria-label="Time picker"
    >
      <div class="grid grid-cols-2 gap-2">
        <div class="max-h-[220px] overflow-auto rounded-lg border border-border/50 bg-[rgba(255,255,255,0.04)] p-1">
          {#each hours as hh (hh)}
            <button
              type="button"
              class={[
                'w-full text-center px-2 py-2 rounded-lg text-[12px] font-mono tabular-nums transition-colors',
                hh === parts.hh ? 'bg-blue text-white' : 'hover:bg-glass2 text-text0'
              ].join(' ')}
              onclick={() => setHour(hh)}
            >
              {hh}
            </button>
          {/each}
        </div>
        <div class="max-h-[220px] overflow-auto rounded-lg border border-border/50 bg-[rgba(255,255,255,0.04)] p-1">
          {#each minutes as mm (mm)}
            <button
              type="button"
              class={[
                'w-full text-center px-2 py-2 rounded-lg text-[12px] font-mono tabular-nums transition-colors',
                mm === parts.mm ? 'bg-blue text-white' : 'hover:bg-glass2 text-text0'
              ].join(' ')}
              onclick={() => setMinute(mm)}
            >
              {mm}
            </button>
          {/each}
        </div>
      </div>
    </div>
  {/if}
</div>

