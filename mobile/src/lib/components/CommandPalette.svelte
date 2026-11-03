<script lang="ts">
  /**
   * ⌘K "Search or ask" palette (design: WideNav). Jumps to pages, settings and recent
   * workouts; with text and no match (or "Ask coach" picked) it opens the coach with the
   * question in the composer.
   */
  import { tick } from 'svelte';
  import { format } from 'date-fns';
  import { navTo } from '$lib/nav';
  import { api } from '$lib/api';
  import { commandPalette } from '$lib/stores/commandPalette.svelte';
  import { PALETTE_PAGES, filterPalette, groupPalette, type PaletteRow } from '$lib/wideNav';

  let { left = 264 }: { left?: number } = $props();

  let query = $state('');
  let active = $state(0);
  let inputEl = $state<HTMLInputElement | null>(null);
  let workoutRows = $state<PaletteRow[]>([]);
  let workoutsLoaded = false;

  type ApiWorkout = { id: string; sport?: string; title?: string; started_at?: string; duration_seconds?: number; tss?: number };

  function sportTag(sport: string | undefined): string {
    const s = (sport || '').toLowerCase();
    if (s.includes('ride') || s.includes('bik') || s.includes('cycl')) return 'BIKE';
    if (s.includes('run')) return 'RUN';
    if (s.includes('swim')) return 'SWIM';
    if (s.includes('strength') || s.includes('gym') || s.includes('weight')) return 'GYM';
    return 'WKT';
  }

  function dur(sec: number | undefined): string {
    if (!sec || sec <= 0) return '';
    const m = Math.round(sec / 60);
    return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}` : `${m}m`;
  }

  async function loadWorkouts() {
    if (workoutsLoaded) return;
    workoutsLoaded = true;
    const rows = ((await api.getCompletedWorkouts(30)) ?? []) as ApiWorkout[];
    workoutRows = rows.map((w) => {
      const when = w.started_at ? format(new Date(w.started_at), 'EEE d MMM') : '';
      const hint = [when, dur(w.duration_seconds), w.tss ? `${Math.round(w.tss)} TSS` : ''].filter(Boolean).join(' · ');
      return { group: 'WORKOUTS', tag: sportTag(w.sport), label: w.title || 'Workout', hint, href: `/training?workout_id=${encodeURIComponent(w.id)}` };
    });
  }

  $effect(() => {
    if (!commandPalette.open) return;
    query = '';
    active = 0;
    void loadWorkouts();
    void tick().then(() => inputEl?.focus());
  });

  const q = $derived(query.trim());
  const hits = $derived(
    filterPalette([...PALETTE_PAGES, ...(q ? workoutRows : workoutRows.slice(0, 3))], query)
  );
  const groups = $derived(groupPalette(hits));
  /** Flat order for arrow keys: "Ask coach" (when typing) then every hit. */
  const flat = $derived<({ kind: 'ask' } | { kind: 'row'; row: PaletteRow })[]>([
    ...(q ? [{ kind: 'ask' as const }] : []),
    ...hits.map((row) => ({ kind: 'row' as const, row }))
  ]);
  // Highlight the first page/workout match; with no match, "Ask coach" (row 0).
  $effect(() => {
    active = q && hits.length ? 1 : 0;
  });

  function close() {
    commandPalette.hide();
  }

  function askCoach() {
    close();
    navTo(`/chat?prompt=${encodeURIComponent(q.slice(0, 2000))}`);
  }

  function open(row: PaletteRow) {
    close();
    navTo(row.href);
  }

  function choose(i: number) {
    const item = flat[i];
    if (!item) {
      if (q) askCoach();
      return;
    }
    if (item.kind === 'ask') askCoach();
    else open(item.row);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      active = Math.min(active + 1, Math.max(flat.length - 1, 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(active - 1, 0);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(active);
    }
  }

  function indexOf(row: PaletteRow): number {
    return flat.findIndex((f) => f.kind === 'row' && f.row === row);
  }
</script>

{#if commandPalette.open}
  <div class="fixed inset-0 z-[60] bg-[rgba(6,6,8,0.62)]" aria-hidden="true" onclick={close}></div>
  <div
    role="dialog"
    aria-modal="true"
    aria-label="Search or ask"
    class="fixed top-6 z-[61] w-[600px] max-w-[calc(100vw-120px)] rounded-[20px] bg-popover border border-popover-border shadow-[0_24px_60px_rgba(0,0,0,0.55)] overflow-hidden text-text0"
    style="left: {left}px"
  >
    <div class="relative flex items-center gap-2.5 px-4 h-14 border-b border-border">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text2"><circle cx="11" cy="11" r="6.5"></circle><path d="m20 20-4-4"></path></svg>
      <label for="palette-q" class="sr-only">Search or ask</label>
      <input
        id="palette-q"
        bind:this={inputEl}
        bind:value={query}
        autocomplete="off"
        role="combobox"
        aria-expanded="true"
        aria-controls="palette-list"
        aria-activedescendant={flat.length ? `palette-opt-${active}` : undefined}
        placeholder="Search pages and workouts, or ask your coach…"
        class="flex-1 min-w-0 h-10 border-0 bg-transparent text-text0 text-[15px] outline-none placeholder:text-text3"
        onkeydown={onKey}
      />
      <button type="button" class="h-[26px] px-2 rounded-[7px] border border-popover-border bg-transparent text-text2 font-mono text-[10px] cursor-pointer" onclick={close}>ESC</button>
    </div>

    <div id="palette-list" role="listbox" aria-label="Results" class="max-h-[420px] overflow-y-auto p-2 flex flex-col gap-0.5">
      {#if q}
        <button
          type="button"
          id="palette-opt-0"
          role="option"
          aria-selected={active === 0}
          class="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-accent-surface border border-accent-surface-border text-left cursor-pointer {active === 0 ? 'ring-1 ring-blue/60' : ''}"
          onmouseenter={() => (active = 0)}
          onclick={askCoach}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="text-blue flex-none"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"></path></svg>
          <span class="flex-1 min-w-0 text-[14px] text-text0 truncate">Ask coach: <span class="text-blue">“{q}”</span></span>
          <span class="font-mono text-[10px] text-text2">↵</span>
        </button>
      {/if}
      {#each groups as g (g.name)}
        <span class="px-3 pt-2.5 pb-1 font-mono text-[10px] tracking-[0.14em] text-text3">{g.name}</span>
        {#each g.rows as r (r.href + r.label)}
          {@const i = indexOf(r)}
          <button
            type="button"
            id="palette-opt-{i}"
            role="option"
            aria-selected={active === i}
            class="flex items-center gap-3 px-3 py-[9px] rounded-xl border-0 text-left cursor-pointer text-text0 {active === i ? 'bg-glass2' : 'bg-transparent'}"
            onmouseenter={() => (active = i)}
            onclick={() => open(r)}
          >
            <span aria-hidden="true" class="flex-none w-[30px] h-[30px] rounded-[9px] bg-bg3 flex items-center justify-center font-mono text-[9px] text-text1">{r.tag}</span>
            <span class="flex-1 min-w-0 flex flex-col gap-px">
              <span class="text-[14px] truncate">{r.label}</span>
              {#if r.hint}<span class="text-[12px] text-text2 truncate">{r.hint}</span>{/if}
            </span>
            {#if r.key}<span class="font-mono text-[10px] text-text3">{r.key}</span>{/if}
          </button>
        {/each}
      {/each}
      {#if q && hits.length === 0}
        <span class="px-3 py-[18px] text-[13px] text-text2">No pages or workouts match. Press Enter to ask your coach instead.</span>
      {/if}
    </div>

    <div class="flex gap-4 px-4 py-2.5 border-t border-border font-mono text-[10px] text-text3">
      <span>1–5 JUMP TO SECTION</span><span>↑↓ MOVE</span><span>↵ OPEN</span><span>ESC CLOSE</span>
    </div>
  </div>
{/if}
