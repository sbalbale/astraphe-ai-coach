<script lang="ts">
  /** Wide Plan week: seven tall day columns with each session's profile and first steps. */
  import { format } from 'date-fns';
  import { fmtDur, fmtHoursMinutes, isMovable, totals, type WideSession } from './planWide';

  let {
    days,
    byIso,
    selectedIso,
    todayIso,
    dragId,
    onpick,
    ondragstart,
    ondragend,
    ondrop
  }: {
    days: Date[];
    byIso: Record<string, WideSession[]>;
    selectedIso: string;
    todayIso: string;
    dragId: string | null;
    onpick: (iso: string) => void;
    ondragstart: (id: string) => void;
    ondragend: () => void;
    ondrop: (fromId: string, toIso: string) => void;
  } = $props();

  const zoneColor = (z: number) => (z > 0 ? `var(--zone-${z})` : 'var(--text2)');
  const t = $derived(totals(days, byIso));
</script>

<div class="flex-1 min-h-[360px] grid grid-cols-7 gap-2">
  {#each days as d (d.toISOString())}
    {@const iso = format(d, 'yyyy-MM-dd')}
    {@const items = byIso[iso] ?? []}
    {@const first = items[0]}
    {@const past = iso < todayIso}
    {@const today = iso === todayIso}
    {@const sel = iso === selectedIso}
    {@const movable = first ? isMovable(first, todayIso) : false}
    {@const dropTarget = dragId !== null && !past}
    <button
      type="button"
      draggable={movable}
      aria-pressed={sel}
      aria-label="{format(d, 'EEEE d MMM')}: {first ? first.title : 'rest'}{first?.completed ? ', completed' : ''}{items.length > 1 ? `, ${items.length} sessions` : ''}"
      class="h-full min-h-0 p-3 gap-2 overflow-hidden rounded-[14px] flex flex-col items-start text-left text-text0 transition-colors {movable ? 'cursor-grab' : 'cursor-pointer'} {sel
        ? 'bg-accent-surface border border-blue'
        : today
          ? 'bg-bg2 border border-accent-surface-border hover:border-text3'
          : dropTarget
            ? 'bg-bg1 border border-dashed border-text3'
            : 'bg-bg1 border border-rail-border hover:border-text3'}"
      onclick={() => onpick(iso)}
      ondragstart={(e) => {
        if (!movable || !first) {
          e.preventDefault();
          return;
        }
        e.dataTransfer?.setData('text/plain', first.id);
        if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
        ondragstart(first.id);
      }}
      ondragend={ondragend}
      ondragover={(e) => {
        if (!past && dragId !== null) e.preventDefault();
      }}
      ondrop={(e) => {
        e.preventDefault();
        const from = e.dataTransfer?.getData('text/plain') || dragId;
        if (from && !past) ondrop(from, iso);
      }}
    >
      <span class="font-mono text-[11px] tracking-[0.08em] uppercase {today ? 'text-blue' : 'text-text2'}">{format(d, 'EEE d')}</span>
      {#if first}
        <span aria-hidden="true" class="block w-full h-[3px] rounded-sm shrink-0" style="background: {zoneColor(first.zone)}; opacity: {past ? 0.4 : 1}"></span>
        <span class="text-[14px] font-medium leading-[1.25] line-clamp-3 {past ? 'text-text2' : 'text-text0'}">{first.title}</span>
        <span class="font-mono text-[11px] text-text2">{fmtDur(first.durationMin)}{first.tss ? ` · ${first.tss}` : ''}</span>
        {#if first.bars.length}
          <span aria-hidden="true" class="flex items-end gap-0.5 h-12 w-full shrink-0">
            {#each first.bars as b, i (i)}
              <span class="block rounded-[3px] {b.hard ? 'bg-blue' : 'bg-text3/60'}" style="flex: {b.minutes} 1 0; height: {b.pct}%; opacity: {past ? 0.5 : 1}"></span>
            {/each}
          </span>
        {/if}
        {#if first.steps.length}
          <span class="flex flex-col gap-1.5 w-full">
            {#each first.steps.slice(0, 3) as st, i (i)}
              <span class="flex justify-between gap-1.5 text-[11px] text-text1 border-t border-rail-border pt-1.5">
                <span class="truncate">{st.name}</span>
                <span class="font-mono text-text2 shrink-0">{st.minutes ? fmtDur(st.minutes) : ''}</span>
              </span>
            {/each}
          </span>
        {/if}
        {#if items.length > 1}
          <span class="font-mono text-[10px] text-text2">+{items.length - 1} more</span>
        {/if}
        {#if first.completed}<span class="mt-auto text-[11px] text-green">✓ done</span>{/if}
      {:else}
        <span class="text-[14px] font-medium text-text2">Rest</span>
      {/if}
    </button>
  {/each}
</div>
<div class="flex justify-between gap-4 font-mono text-[11px] text-text2">
  <span>{t.tss} TSS · {fmtHoursMinutes(t.minutes)} PLANNED</span>
  <span class="truncate">DRAG A SESSION ONTO ANOTHER DAY TO MOVE IT</span>
</div>
