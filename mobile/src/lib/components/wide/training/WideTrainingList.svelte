<script lang="ts">
  /**
   * Wide Training log, master pane (design: WTraining list): title + log button, the week
   * summary with its navigator, the week's activities, and the load note.
   */
  import { format } from 'date-fns';
  import WeekNavigator from '$lib/components/WeekNavigator.svelte';
  import type { Units } from '$lib/utils/units';
  import { activityMeta, getWorkoutLabel, positiveRounded, sportGlyph } from '$lib/utils/trainingFormat';

  let {
    weekValue = $bindable(),
    eyebrow,
    workouts,
    totals,
    weeklyTarget,
    selectedId,
    loadInsight,
    units,
    widthClass = 'w-[360px]',
    onSelect,
    onIntent,
    onLog
  }: {
    /** Any `yyyy-MM-dd` inside the shown week. */
    weekValue: string;
    eyebrow: string;
    workouts: Record<string, any>[];
    totals: { tss: number; time: string; distance: string; distanceUnit: string };
    weeklyTarget: number;
    selectedId: string | null;
    loadInsight: string | null;
    units: Units;
    widthClass?: string;
    onSelect: (w: Record<string, any>) => void;
    onIntent?: (id: string) => void;
    onLog: () => void;
  } = $props();
</script>

<section
  aria-label="Activities"
  class="flex-none {widthClass} box-border h-full overflow-y-auto pt-8 px-5 pb-6 border-r border-rail-border flex flex-col gap-3.5"
>
  <div class="flex justify-between items-end">
    <div class="flex flex-col gap-1">
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2">{eyebrow}</span>
      <h1 class="m-0 font-display font-normal text-[36px] leading-none">Training</h1>
    </div>
    <button
      type="button"
      aria-label="Log activity"
      class="w-10 h-10 rounded-xl border-0 bg-blue text-on-accent flex items-center justify-center cursor-pointer"
      onclick={onLog}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
    </button>
  </div>

  <section aria-label="Week summary" class="bg-bg2 border border-border rounded-[20px] px-3.5 pt-3 pb-3.5 flex flex-col gap-3">
    <WeekNavigator bind:value={weekValue} max={format(new Date(), 'yyyy-MM-dd')} />
    <div class="grid grid-cols-3 gap-2">
      <div class="flex flex-col gap-0.5">
        <span class="text-[20px] font-medium tracking-[-0.02em]">{totals.tss}{#if weeklyTarget}<span class="text-xs text-text2 font-normal"> / {weeklyTarget}</span>{/if}</span>
        <span class="text-[11px] text-text2">TSS</span>
      </div>
      <div class="flex flex-col gap-0.5">
        <span class="text-[20px] font-medium tracking-[-0.02em]">{workouts.length ? totals.time : '—'}</span>
        <span class="text-[11px] text-text2">Time</span>
      </div>
      <div class="flex flex-col gap-0.5">
        <span class="text-[20px] font-medium tracking-[-0.02em]">{#if workouts.length}{totals.distance}<span class="text-xs text-text2 font-normal"> {totals.distanceUnit}</span>{:else}—{/if}</span>
        <span class="text-[11px] text-text2">Distance</span>
      </div>
    </div>
    {#if weeklyTarget}
      <div aria-hidden="true" class="h-1.5 rounded-[3px] bg-border overflow-hidden">
        <div class="h-1.5 rounded-[3px] bg-blue" style="width: {Math.min(100, Math.round((totals.tss / weeklyTarget) * 100))}%"></div>
      </div>
    {/if}
  </section>

  {#if workouts.length}
    <ul class="list-none m-0 p-0 flex flex-col gap-1.5">
      {#each workouts as w (w?.id ?? w?.started_at)}
        {@const on = selectedId != null && String(w?.id) === selectedId}
        {@const tss = positiveRounded(w?.tss)}
        <li>
          <button
            type="button"
            aria-pressed={on}
            class="w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-left text-text0 cursor-pointer border {on ? 'bg-popover border-accent-surface-border' : 'bg-transparent border-transparent hover:bg-bg1'}"
            onclick={() => onSelect(w)}
            onmouseenter={() => w?.id && onIntent?.(String(w.id))}
          >
            <span aria-hidden="true" class="flex-none w-[38px] h-[38px] rounded-[11px] flex items-center justify-center font-mono text-[10px] font-medium {on ? 'bg-accent-surface text-blue' : 'bg-bg3 text-text1'}">{sportGlyph(w?.sport)}</span>
            <span class="flex-1 min-w-0 flex flex-col gap-0.5">
              <span class="text-[14px] font-medium truncate">{w?.title || `${getWorkoutLabel(w?.sport)} Session`}</span>
              <span class="text-[12px] text-text2 truncate">{activityMeta(w, units)}</span>
            </span>
            <span class="flex flex-col items-end gap-0.5">
              <span class="font-mono text-[13px]">{tss ?? '—'}</span>
              <span class="text-[10px] text-text2">TSS</span>
            </span>
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    <div class="px-4 py-6 rounded-[18px] border border-dashed border-popover-border text-center text-[13px] leading-[1.5] text-text2">
      Nothing logged this week yet.<br />Activities from Garmin and WHOOP appear here automatically.
    </div>
  {/if}

  {#if loadInsight}
    <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-popover-border">
      <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">LOAD</span>
      <span class="text-[13px] leading-[1.45] text-text1">{loadInsight}</span>
    </div>
  {/if}
</section>
