<script lang="ts">
  /** Wide Plan month grid: 7 day cells + a weekly TSS column; sessions drag onto other days. */
  import { format, isSameMonth } from 'date-fns';
  import { fmtDur, isMovable, totals, type WideSession } from './planWide';

  let {
    weeks,
    viewMonth,
    byIso,
    selectedIso,
    todayIso,
    dragId,
    onpick,
    ondragstart,
    ondragend,
    ondrop
  }: {
    weeks: Date[][];
    viewMonth: Date;
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

  function weekLabel(days: Date[]): string {
    const first = format(days[0], 'yyyy-MM-dd');
    const last = format(days[6], 'yyyy-MM-dd');
    return todayIso >= first && todayIso <= last ? 'THIS WK' : '';
  }
</script>

<div aria-hidden="true" class="grid grid-cols-[repeat(7,minmax(0,1fr))_64px] gap-1.5 font-mono text-[10px] tracking-[0.1em] text-text2">
  <span>MON</span><span>TUE</span><span>WED</span><span>THU</span><span>FRI</span><span>SAT</span><span>SUN</span><span class="text-right">TSS</span>
</div>
<div class="flex-1 min-h-0 flex flex-col gap-1.5">
  {#each weeks as days (days[0].toISOString())}
    {@const t = totals(days, byIso)}
    <div class="flex-1 min-h-[88px] grid grid-cols-[repeat(7,minmax(0,1fr))_64px] gap-1.5">
      {#each days as d (d.toISOString())}
        {@const iso = format(d, 'yyyy-MM-dd')}
        {@const items = byIso[iso] ?? []}
        {@const first = items[0]}
        {@const past = iso < todayIso}
        {@const today = iso === todayIso}
        {@const sel = iso === selectedIso}
        {@const inMonth = isSameMonth(d, viewMonth)}
        {@const movable = first ? isMovable(first, todayIso) : false}
        {@const dropTarget = dragId !== null && !past}
        <button
          type="button"
          draggable={movable}
          aria-pressed={sel}
          aria-label="{format(d, 'EEE d MMM')}: {first ? first.title : 'rest'}{first?.completed ? ', completed' : ''}{items.length > 1 ? `, ${items.length} sessions` : ''}"
          class="h-full min-h-0 p-2.5 gap-1.5 overflow-hidden rounded-[14px] flex flex-col items-start text-left text-text0 transition-colors {movable ? 'cursor-grab' : 'cursor-pointer'} {sel
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
          <span class="flex justify-between w-full">
            <span class="font-mono text-[11px] {today ? 'font-bold text-blue' : inMonth ? 'font-medium text-text1' : 'font-medium text-text3'}">{format(d, 'd')}</span>
            {#if first?.completed}<span class="text-[10px] text-green">✓ done</span>{/if}
          </span>
          {#if first}
            <span aria-hidden="true" class="block w-full h-[3px] rounded-sm shrink-0" style="background: {zoneColor(first.zone)}; opacity: {past ? 0.4 : 1}"></span>
            <span class="text-[12px] font-medium leading-[1.25] line-clamp-2 {past ? 'text-text2' : 'text-text0'}">{first.title}</span>
            <span class="font-mono text-[10px] text-text2 truncate max-w-full">{fmtDur(first.durationMin)}{first.tss ? ` · ${first.tss}` : ''}{items.length > 1 ? ` · +${items.length - 1}` : ''}</span>
          {/if}
        </button>
      {/each}
      <span class="flex flex-col items-end justify-center gap-0.5">
        <span class="font-mono text-[13px]">{t.tss}</span>
        <span class="text-[10px] text-text2">{weekLabel(days)}</span>
      </span>
    </div>
  {/each}
</div>
