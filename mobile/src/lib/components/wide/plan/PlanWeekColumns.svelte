<script lang="ts">
  import { formatStepDuration } from '$lib/utils/stepDuration';
  /** Wide Plan week: seven tall day columns with each session's profile and first steps. */
  import { format } from 'date-fns';
  import { fmtDur, fmtHoursMinutes, totals, type WideSession } from './planWide';
  import PlanSessionChip from './PlanSessionChip.svelte';

  let {
    days,
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
    days: Date[];
    byIso: Record<string, WideSession[]>;
    selectedIso: string;
    todayIso: string;
    dragId: string | null;
    selectedId?: string | null;
    onpick: (iso: string) => void;
    onpicksession: (iso: string, id: string) => void;
    ondragstart: (id: string) => void;
    ondragend: () => void;
    ondrop: (fromId: string, toIso: string) => void;
  } = $props();

  const t = $derived(totals(days, byIso));
</script>

<div class="flex-1 min-h-[360px] grid grid-cols-7 gap-2">
  {#each days as d (d.toISOString())}
    {@const iso = format(d, 'yyyy-MM-dd')}
    {@const items = byIso[iso] ?? []}
    {@const past = iso < todayIso}
    {@const today = iso === todayIso}
    {@const sel = iso === selectedIso}
    {@const dropTarget = dragId !== null && !past}
    <div
      role="button"
      tabindex="0"
      aria-pressed={sel}
      aria-label="{format(d, 'EEEE d MMM')}: {items.length ? items.map((s) => s.title).join(', ') : 'rest'}"
      class="h-full min-h-0 p-3 gap-2 overflow-y-auto rounded-[14px] flex flex-col items-start text-left text-text0 cursor-pointer transition-colors {sel
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
      <span class="font-mono text-[11px] tracking-[0.08em] uppercase {today ? 'text-blue' : 'text-text2'}">{format(d, 'EEE d')}</span>
      {#each items as s (s.id)}
        <PlanSessionChip
          {s}
          {todayIso}
          {past}
          size="md"
          showBars
          selected={sel && s.id === selectedId}
          onpick={() => onpicksession(iso, s.id)}
          {ondragstart}
          {ondragend}
        />
        {#if items.length === 1 && s.steps.length}
          <span class="flex flex-col gap-1.5 w-full">
            {#each s.steps.slice(0, 3) as st, i (i)}
              <span class="flex justify-between gap-1.5 text-[11px] text-text1 border-t border-rail-border pt-1.5">
                <span class="truncate">{st.name}</span>
                <span class="font-mono text-text2 shrink-0">{st.minutes ? formatStepDuration(st.minutes) : ''}</span>
              </span>
            {/each}
          </span>
        {/if}
      {:else}
        <span class="text-[14px] font-medium text-text2">Rest</span>
      {/each}
    </div>
  {/each}
</div>
<div class="flex justify-between gap-4 font-mono text-[11px] text-text2">
  <span>{t.tss} TSS · {fmtHoursMinutes(t.minutes)} PLANNED</span>
  <span class="truncate">DRAG A SESSION ONTO ANOTHER DAY TO MOVE IT</span>
</div>
