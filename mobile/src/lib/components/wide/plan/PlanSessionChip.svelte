<script lang="ts">
  /** One session inside a calendar day (month cell or week column): zone bar, title, meta,
   *  done tick. Its own button, so a day with several sessions shows and selects each one;
   *  drag it onto another day to move it. */
  import { fmtDur, isMovable, type WideSession } from './planWide';
  import PlanDayMark from '$lib/components/linking/PlanDayMark.svelte';
  import { dayMark, sessionLinkState } from '$lib/utils/linking';

  let {
    s,
    todayIso,
    past,
    selected = false,
    size = 'sm',
    showBars = false,
    onpick,
    ondragstart,
    ondragend
  }: {
    s: WideSession;
    todayIso: string;
    past: boolean;
    selected?: boolean;
    size?: 'sm' | 'md';
    showBars?: boolean;
    onpick: () => void;
    ondragstart: (id: string) => void;
    ondragend: () => void;
  } = $props();

  const movable = $derived(isMovable(s, todayIso));
  /** Linked (filled tick) / done without a workout (ring tick) / missed (dashed ring). */
  const mark = $derived(
    dayMark(sessionLinkState({ completed: s.completed, completed_workout_id: s.completedWorkoutId, date: s.isoDate }, todayIso))
  );
  const zoneColor = (z: number) => (z > 0 ? `var(--zone-${z})` : 'var(--text2)');
</script>

<button
  type="button"
  draggable={movable}
  aria-pressed={selected}
  aria-label="{s.title}{mark === 'linked' ? ', done, linked' : mark === 'mark' ? ', done, no workout' : mark === 'missed' ? ', missed' : ''}"
  class="w-full min-w-0 flex flex-col items-start gap-1 text-left rounded-[8px] px-1 py-1 -mx-1 transition-colors {movable ? 'cursor-grab' : 'cursor-pointer'} {selected ? 'bg-glass2' : 'hover:bg-glass'}"
  onclick={(e) => {
    e.stopPropagation();
    onpick();
  }}
  ondragstart={(e) => {
    if (!movable) {
      e.preventDefault();
      return;
    }
    e.stopPropagation();
    e.dataTransfer?.setData('text/plain', s.id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
    ondragstart(s.id);
  }}
  {ondragend}
>
  <span aria-hidden="true" class="block w-full h-[3px] rounded-sm shrink-0" style="background: {zoneColor(s.zone)}; opacity: {past ? 0.4 : 1}"></span>
  <span class="w-full font-medium leading-[1.25] line-clamp-2 {size === 'md' ? 'text-[13px]' : 'text-[12px]'} {past && !s.completed ? 'text-text2' : 'text-text0'}">{s.title}</span>
  <span class="w-full flex justify-between gap-1 font-mono {size === 'md' ? 'text-[11px]' : 'text-[10px]'} text-text2">
    <span class="truncate">{fmtDur(s.durationMin)}{s.tss ? ` · ${s.tss}` : ''}</span>
    {#if mark}<PlanDayMark {mark} size={size === 'md' ? 14 : 12} />{/if}
  </span>
  {#if showBars && s.bars.length}
    <span aria-hidden="true" class="flex items-end gap-0.5 h-10 w-full shrink-0">
      {#each s.bars as b, i (i)}
        <span class="block rounded-[3px] {b.hard ? 'bg-blue' : 'bg-text3/60'}" style="flex: {b.minutes} 1 0; height: {b.pct}%; opacity: {past ? 0.5 : 1}"></span>
      {/each}
    </span>
  {/if}
</button>
