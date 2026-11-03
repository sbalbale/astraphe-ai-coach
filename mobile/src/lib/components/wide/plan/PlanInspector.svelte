<script lang="ts">
  import { formatStepDuration } from '$lib/utils/stepDuration';
  /**
   * Wide Plan inspector (right column): the selected day's session, its stats and steps,
   * plus Move (to another day this week; swaps when that day has a session), Swap (ask the
   * coach for a different session) and Remove.
   */
  import { format } from 'date-fns';
  import { fmtDur, isMovable, type WideSession } from './planWide';

  let {
    date,
    todayIso,
    sessions,
    selected,
    weekDays,
    byIso,
    saving = false,
    error = null,
    toast = null,
    narrow = false,
    onselect,
    onmove,
    onswap,
    onadd,
    onremove,
    ontoggledone,
    onopen,
    onundo,
    ondismiss
  }: {
    date: Date;
    todayIso: string;
    sessions: WideSession[];
    selected: WideSession | null;
    weekDays: Date[];
    byIso: Record<string, WideSession[]>;
    saving?: boolean;
    error?: string | null;
    toast?: { message: string; canUndo: boolean } | null;
    narrow?: boolean;
    onselect: (id: string) => void;
    onmove: (toIso: string) => void;
    onswap: () => void;
    onadd: () => void;
    onremove: () => void;
    /** Marks the selected session done / not done. */
    ontoggledone: () => void;
    onopen: () => void;
    onundo: () => void;
    ondismiss: () => void;
  } = $props();

  let moveOpen = $state(false);
  $effect(() => {
    void selected?.id;
    moveOpen = false;
  });

  const iso = $derived(format(date, 'yyyy-MM-dd'));
  const past = $derived(iso < todayIso);
  const s = $derived(selected);
  const done = $derived(Boolean(s?.completed));
  const kicker = $derived(
    `${format(date, 'EEE d MMM')}${iso === todayIso ? ' · Today' : done ? ' · Completed' : past ? ' · Past' : ''}`
  );
  const zoneColor = (z: number) => (z > 0 ? `var(--zone-${z})` : 'var(--text2)');

  /** One-line summary from the coach's markdown description. */
  function plainText(md: string): string {
    return md
      .split('\n')
      .filter((l) => !l.trim().startsWith('|'))
      .join(' ')
      .replace(/[#*_>`]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 320);
  }

  const peakZone = $derived(
    s ? Math.max(s.zone, ...s.steps.map((x) => x.zone), 0) : 0
  );
  const moveTargets = $derived(
    s
      ? weekDays
          .map((d) => ({ d, iso: format(d, 'yyyy-MM-dd') }))
          .filter((x) => x.iso !== s.isoDate && x.iso >= todayIso)
          .map((x) => {
            const there = (byIso[x.iso] ?? []).find((o) => o.id !== s.id);
            const swaps = Boolean(there && isMovable(there, todayIso));
            return {
              iso: x.iso,
              label: format(x.d, 'EEE d MMM'),
              hint: there ? (swaps ? `Swaps with ${there.title.toLowerCase()}` : `Joins ${there.title.toLowerCase()}`) : 'Currently rest',
              color: there ? zoneColor(there.zone) : 'var(--bg3)'
            };
          })
      : []
  );
  const canAct = $derived(Boolean(s) && !done && !past);
</script>

<aside
  aria-label="Selected day"
  class="relative flex-none box-border h-full overflow-y-auto border-l border-rail-border bg-rail flex flex-col gap-4 {narrow ? 'w-[300px] px-5 py-8' : 'w-[340px] px-6 py-8'}"
>
  <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{kicker}</span>

  {#if sessions.length > 1}
    <div role="tablist" aria-label="Sessions this day" class="flex flex-wrap gap-1.5">
      {#each sessions as o (o.id)}
        <button
          type="button"
          role="tab"
          aria-selected={o.id === s?.id}
          class="h-8 px-3 rounded-full border text-[12px] cursor-pointer max-w-full truncate {o.id === s?.id ? 'bg-border border-border text-text0' : 'bg-transparent border-border text-text2'}"
          onclick={() => onselect(o.id)}
        >{o.title}</button>
      {/each}
    </div>
  {/if}

  <h2 class="m-0 font-display font-normal text-[32px] leading-[1.05]">{s ? s.title : 'Rest day'}</h2>
  {#if s}
    {#if s.context}
      <p class="m-0 text-[14px] leading-[1.5] text-text1">{plainText(s.context)}</p>
    {/if}
    <dl class="m-0 grid grid-cols-3 gap-1.5">
      <div class="bg-popover rounded-xl p-2.5 flex flex-col-reverse gap-0.5"><dt class="text-[10px] text-text2">Duration</dt><dd class="m-0 text-[16px] font-medium">{s.durationMin ? fmtDur(s.durationMin) : '—'}</dd></div>
      <div class="bg-popover rounded-xl p-2.5 flex flex-col-reverse gap-0.5"><dt class="text-[10px] text-text2">{done ? 'TSS' : 'Est. TSS'}</dt><dd class="m-0 text-[16px] font-medium">{s.tss ?? '—'}</dd></div>
      <div class="bg-popover rounded-xl p-2.5 flex flex-col-reverse gap-0.5"><dt class="text-[10px] text-text2">Zone</dt><dd class="m-0 text-[16px] font-medium">{peakZone > 0 ? `Z${peakZone}` : '—'}</dd></div>
    </dl>
    {#if s.steps.length}
      <ol aria-label="Steps" class="list-none m-0 p-0 flex flex-col">
        {#each s.steps as st, i (i)}
          <li class="grid grid-cols-[4px_1fr_auto_40px] gap-2.5 items-center py-2.5 border-t border-rail-border text-[13px]">
            <span aria-hidden="true" class="w-1 h-[22px] rounded-sm" style="background: {zoneColor(st.zone)}"></span>
            <span class="min-w-0 truncate">{st.name}</span>
            <span class="font-mono text-[11px] text-text1">{st.target ?? ''}</span>
            <span class="text-right font-mono text-[11px] text-text2">{st.minutes ? formatStepDuration(st.minutes) : ''}</span>
          </li>
        {/each}
      </ol>
    {/if}
    <button type="button" class="self-start p-0 border-0 bg-transparent text-[13px] text-blue cursor-pointer" onclick={onopen}>
      Open full session · tap blocks for detail
    </button>
  {:else}
    <p class="m-0 text-[14px] leading-[1.5] text-text1">{past ? 'Nothing was planned this day.' : 'Nothing planned. Sleep in, eat well.'}</p>
  {/if}

  {#if toast}
    <div role="status" class="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-accent-surface border border-accent-surface-border text-[13px]">
      <span class="flex-1">{toast.message}</span>
      {#if toast.canUndo}
        <button type="button" disabled={saving} class="h-7 px-2 border-0 bg-transparent text-blue text-[13px] font-semibold cursor-pointer disabled:opacity-50" onclick={onundo}>Undo</button>
      {:else}
        <button type="button" aria-label="Dismiss" class="h-7 px-2 border-0 bg-transparent text-text2 cursor-pointer" onclick={ondismiss}>×</button>
      {/if}
    </div>
  {/if}
  {#if error}
    <p role="alert" class="m-0 text-[13px] text-red">{error}</p>
  {/if}

  {#if s}
    <button
      type="button"
      aria-pressed={done}
      disabled={saving}
      class="mt-auto shrink-0 h-[42px] rounded-xl text-[13px] font-medium cursor-pointer flex items-center justify-center gap-2 disabled:opacity-50 {done ? 'border border-green/40 bg-green-dim text-green' : 'border border-popover-border bg-transparent text-text0 hover:border-text3'}"
      onclick={ontoggledone}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"></path></svg>
      {done ? 'Done · tap to undo' : 'Mark as done'}
    </button>
  {/if}

  {#if canAct || (!s && !past)}
    <div class="relative {s ? '' : 'mt-auto'} flex flex-col gap-2">
      {#if moveOpen && s}
        <div role="menu" aria-label="Move to" class="absolute left-0 right-0 bottom-[calc(100%+8px)] z-30 p-2 rounded-[18px] bg-popover border border-popover-border shadow-[0_18px_44px_rgba(0,0,0,0.5)] flex flex-col gap-0.5">
          <span class="px-2.5 py-1.5 font-mono text-[10px] tracking-[0.14em] text-text2">MOVE TO (SWAPS DAYS)</span>
          {#if moveTargets.length === 0}
            <span class="px-2.5 py-2 text-[13px] text-text2">No later days left this week.</span>
          {/if}
          {#each moveTargets as m (m.iso)}
            <button
              type="button"
              role="menuitem"
              disabled={saving}
              class="flex items-center gap-2.5 p-2.5 border-0 rounded-xl bg-transparent text-text0 text-[14px] text-left cursor-pointer hover:bg-border disabled:opacity-50"
              onclick={() => {
                moveOpen = false;
                onmove(m.iso);
              }}
            >
              <span aria-hidden="true" class="flex-none w-1 h-[30px] rounded-sm" style="background: {m.color}"></span>
              <span class="flex-1 flex flex-col gap-px"><span>{m.label}</span><span class="text-[12px] text-text2">{m.hint}</span></span>
            </button>
          {/each}
        </div>
      {/if}
      <div class="flex gap-2">
        {#if s}
          <button
            type="button"
            aria-expanded={moveOpen}
            disabled={saving}
            class="flex-1 h-[42px] rounded-xl border border-popover-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer hover:border-text3 disabled:opacity-50"
            onclick={() => (moveOpen = !moveOpen)}
          >{saving ? 'Saving…' : 'Move'}</button>
          <button
            type="button"
            class="flex-1 h-[42px] rounded-xl border border-popover-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer hover:border-text3"
            onclick={onswap}
          >Swap</button>
          <button
            type="button"
            aria-label="Remove from plan"
            disabled={saving}
            class="w-[42px] h-[42px] shrink-0 rounded-xl border border-red/50 bg-transparent text-red flex items-center justify-center cursor-pointer disabled:opacity-50"
            onclick={onremove}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
          </button>
        {:else}
          <button
            type="button"
            class="flex-1 h-[42px] rounded-xl border border-popover-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer hover:border-text3"
            onclick={onadd}
          >Add a session</button>
        {/if}
      </div>
      {#if s}
        <span class="text-center text-[11px] text-text3">Tip: drag a session onto another day to move it</span>
      {/if}
    </div>
  {/if}
</aside>
