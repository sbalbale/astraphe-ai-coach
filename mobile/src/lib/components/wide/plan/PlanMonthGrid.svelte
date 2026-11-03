<script lang="ts">
  import { WEEKDAY_SHORT } from '$lib/utils/week';
  /** Wide Plan month grid: 7 day cells + a weekly TSS column; sessions drag onto other days. */
  import { format, isSameMonth } from 'date-fns';
  import { totals, type WideSession } from './planWide';
  import PlanSessionChip from './PlanSessionChip.svelte';

  let {
    weeks,
    viewMonth,
    byIso,
    selectedIso,
    todayIso,
    dragId,
    selectedId = null,
    onpick,
    onpicksession,
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
    /** The session shown in the inspector (highlighted in its day). */
    selectedId?: string | null;
    onpick: (iso: string) => void;
    /** Pick one session of a day (days can hold several). */
    onpicksession: (iso: string, id: string) => void;
    ondragstart: (id: string) => void;
    ondragend: () => void;
    ondrop: (fromId: string, toIso: string) => void;
  } = $props();

  /** Sessions shown per month cell before "+N more". */
  const MAX_IN_CELL = 3;

  function weekLabel(days: Date[]): string {
    const first = format(days[0], 'yyyy-MM-dd');
    const last = format(days[6], 'yyyy-MM-dd');
    return todayIso >= first && todayIso <= last ? 'THIS WK' : '';
  }
</script>

<div aria-hidden="true" class="grid grid-cols-[repeat(7,minmax(0,1fr))_64px] gap-1.5 font-mono text-[10px] tracking-[0.1em] text-text2">
  {#each WEEKDAY_SHORT as d (d)}<span>{d}</span>{/each}<span class="text-right">TSS</span>
</div>
<div class="flex-1 min-h-0 flex flex-col gap-1.5">
  {#each weeks as days (days[0].toISOString())}
    {@const t = totals(days, byIso)}
    <div class="flex-1 min-h-[88px] grid grid-cols-[repeat(7,minmax(0,1fr))_64px] gap-1.5">
      {#each days as d (d.toISOString())}
        {@const iso = format(d, 'yyyy-MM-dd')}
        {@const items = byIso[iso] ?? []}
        {@const past = iso < todayIso}
        {@const today = iso === todayIso}
        {@const sel = iso === selectedIso}
        {@const inMonth = isSameMonth(d, viewMonth)}
        {@const dropTarget = dragId !== null && !past}
        <div
          role="button"
          tabindex="0"
          aria-pressed={sel}
          aria-label="{format(d, 'EEE d MMM')}: {items.length ? items.map((s) => s.title).join(', ') : 'rest'}"
          class="h-full min-h-0 p-2.5 gap-1 overflow-hidden rounded-[14px] flex flex-col items-start text-left text-text0 cursor-pointer transition-colors {sel
            ? 'bg-accent-surface border border-blue'
            : today
              ? 'bg-bg2 border border-accent-surface-border hover:border-text3'
              : dropTarget
                ? 'bg-bg1 border border-dashed border-text3'
                : 'bg-bg1 border border-rail-border hover:border-text3'}"
          onclick={() => onpick(iso)}
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onpick(iso);
            }
          }}
          ondragover={(e) => {
            if (!past && dragId !== null) e.preventDefault();
          }}
          ondrop={(e) => {
            e.preventDefault();
            const from = e.dataTransfer?.getData('text/plain') || dragId;
            if (from && !past) ondrop(from, iso);
          }}
        >
          <span class="font-mono text-[11px] {today ? 'font-bold text-blue' : inMonth ? 'font-medium text-text1' : 'font-medium text-text3'}">{format(d, 'd')}</span>
          {#each items.slice(0, MAX_IN_CELL) as s (s.id)}
            <PlanSessionChip
              {s}
              {todayIso}
              {past}
              selected={sel && s.id === selectedId}
              onpick={() => onpicksession(iso, s.id)}
              {ondragstart}
              {ondragend}
            />
          {/each}
          {#if items.length > MAX_IN_CELL}
            <span class="font-mono text-[10px] text-text2">+{items.length - MAX_IN_CELL} more</span>
          {/if}
        </div>
      {/each}
      <span class="flex flex-col items-end justify-center gap-0.5">
        <span class="font-mono text-[13px]">{t.tss}</span>
        <span class="text-[10px] text-text2">{weekLabel(days)}</span>
      </span>
    </div>
  {/each}
</div>
