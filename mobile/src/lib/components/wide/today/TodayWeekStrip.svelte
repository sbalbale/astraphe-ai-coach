<script lang="ts">
  /** Wide Today: the week's planned sessions, every one listed per day; picking a day shows them in the session cards. */
  import { resolve } from '$app/paths';
  import { format } from 'date-fns';
  import type { Workout } from '$lib/types/training';
  import { daySessions, shortDuration, weekSummary, zoneNumber } from './todayWide';

  let {
    days,
    byIso,
    selectedIso,
    todayIso,
    onSelect
  }: {
    days: Date[];
    byIso: Record<string, Workout[]>;
    selectedIso: string;
    todayIso: string;
    onSelect: (iso: string) => void;
  } = $props();

  const all = $derived(days.flatMap((d) => byIso[format(d, 'yyyy-MM-dd')] ?? []));
  const summary = $derived(weekSummary(all));

  function chipColor(w: Workout | undefined): string {
    if (!w) return 'transparent';
    if (w.sport === 'strength' || w.sport === 'mobility') return 'var(--text2)';
    const z = zoneNumber(w.primary_zone);
    return z ? `var(--zone-${z})` : 'transparent';
  }
</script>

<section aria-label="This week" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
  <div class="flex justify-between items-baseline">
    <h2 class="m-0 font-display font-normal text-[24px]">This week</h2>
    <span class="flex gap-3.5 items-baseline">
      <span class="font-mono text-[11px] text-text2">{summary}</span>
      <a href={resolve('/plan')} class="text-[12px] text-blue no-underline">Open plan</a>
    </span>
  </div>
  <div class="grid grid-cols-7 gap-2">
    {#each days as d (d.toISOString())}
      {@const iso = format(d, 'yyyy-MM-dd')}
      {@const items = daySessions(byIso[iso] ?? [], iso)}
      {@const first = items[0]}
      {@const on = iso === selectedIso}
      {@const mins = items.reduce((a, w) => a + (w.duration_minutes || 0), 0)}
      {@const tss = items.reduce((a, w) => a + (Number(w.projected_tss) || 0), 0)}
      <button
        type="button"
        aria-pressed={on}
        aria-label="{format(d, 'EEEE')}: {first ? items.map((w) => w.title).join(', ') : 'Rest'}"
        class="min-h-[96px] p-2.5 rounded-[14px] flex flex-col items-start gap-1.5 text-left cursor-pointer text-text0 border {on
          ? 'bg-accent-surface border-blue'
          : 'bg-bg1 border-rail-border hover:border-popover-border'}"
        onclick={() => onSelect(iso)}
      >
        <span class="font-mono text-[10px] tracking-[0.08em] uppercase {iso === todayIso ? 'text-blue' : 'text-text2'}">{format(d, 'EEE d')}</span>
        {#each items as w (w.id)}
          <span class="w-full flex flex-col gap-1">
            <span aria-hidden="true" class="block w-full h-1 rounded-sm" style="background: {chipColor(w)}"></span>
            <span class="text-[12px] font-medium leading-[1.3] line-clamp-2">{w.title}</span>
          </span>
        {:else}
          <span aria-hidden="true" class="block w-full h-1 rounded-sm"></span>
          <span class="text-[12px] font-medium leading-[1.3]">Rest</span>
        {/each}
        <span class="text-[11px] text-text2">{first ? `${shortDuration(mins)}${tss > 0 ? ` · ${Math.round(tss)}` : ''}` : '—'}</span>
      </button>
    {/each}
  </div>
</section>
