<script lang="ts">
  import { format } from 'date-fns';
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import DashedNote from '$lib/components/ui/DashedNote.svelte';
  import UiIcon from '$lib/components/ui/UiIcon.svelte';
  import { workoutEffort, workoutNotes } from '$lib/utils/manualWorkout';
  import { workoutDurationSecs } from '$lib/utils/workoutDuration';

  /**
   * Detail view for a workout logged by hand (design: empty states, page 9): no map,
   * charts or laps, so it's the summary, an explanation, and the athlete's notes.
   * The parent decides when to use it (isManualWorkout) and owns back / edit / delete.
   */
  let {
    workout,
    sportLabel,
    backLabel = 'Training',
    onBack,
    onEdit,
    onDelete,
  }: {
    workout: Record<string, any>;
    /** Display name for the sport, e.g. getWorkoutLabel(sport). */
    sportLabel: string;
    backLabel?: string;
    onBack: () => void;
    onEdit?: () => void;
    onDelete?: () => void;
  } = $props();

  const started = $derived(workout?.started_at ? new Date(workout.started_at) : null);
  const dayLabel = $derived(started && !Number.isNaN(started.getTime()) ? format(started, 'EEE d MMM') : null);
  const secs = $derived(workoutDurationSecs(workout));
  const durationLabel = $derived.by(() => {
    if (secs == null || secs <= 0) return '--';
    const h = Math.floor(secs / 3600);
    const m = Math.round((secs % 3600) / 60);
    return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
  });
  const effort = $derived(workoutEffort(workout));
  const tss = $derived(Number.isFinite(Number(workout?.tss)) && Number(workout.tss) > 0 ? Math.round(Number(workout.tss)) : null);
  const notes = $derived(workoutNotes(workout));

  const tiles = $derived(
    [
      { k: 'Duration', v: durationLabel },
      effort != null ? { k: 'Effort', v: `${effort} / 10` } : null,
      { k: 'Est. TSS', v: tss == null ? '--' : String(tss) },
    ].filter((t): t is { k: string; v: string } => t !== null)
  );
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-center justify-between">
    <button type="button" class="inline-flex items-center gap-2 bg-transparent border-0 p-0 text-[16px] text-text1 cursor-pointer hover:text-text0" onclick={onBack}>
      <UiIcon name="chevron-left" size={18} />
      {backLabel}
    </button>
    <div class="flex items-center gap-2">
      {#if onDelete}
        <button type="button" aria-label="Delete workout" class="w-11 h-11 rounded-[14px] border border-border bg-transparent text-red flex items-center justify-center cursor-pointer" onclick={onDelete}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
        </button>
      {/if}
      {#if onEdit}
        <button type="button" class="h-11 px-4 rounded-[14px] border border-border bg-transparent text-[15px] font-semibold text-text0 cursor-pointer" onclick={onEdit}>Edit</button>
      {/if}
    </div>
  </div>

  <header class="flex flex-col gap-1.5">
    <span class="font-mono text-[12px] tracking-[0.16em] text-blue uppercase">
      {sportLabel}{dayLabel ? ` · ${dayLabel}` : ''} · Logged by hand
    </span>
    <h1 class="m-0 font-display font-normal text-[38px] leading-[1.05] text-text0">{workout?.title || `${sportLabel} session`}</h1>
  </header>

  <dl class="m-0 grid gap-2.5" style="grid-template-columns: repeat({tiles.length}, minmax(0, 1fr));">
    {#each tiles as t (t.k)}
      <div class="bg-bg2 border border-border rounded-[18px] px-4 py-3.5 flex flex-col-reverse gap-0.5">
        <dt class="text-[14px] text-text2">{t.k}</dt>
        <dd class="m-0 text-[22px] font-medium text-text0">{t.v}</dd>
      </div>
    {/each}
  </dl>

  <EmptyStateCard
    icon="pulse"
    tone="neutral"
    align="left"
    eyebrow="Nothing yet"
    title="No heart rate or GPS"
    message="This was logged by hand, so there are no charts, laps or map. Load is estimated from the duration and any heart rate or power you entered. Record with your watch next time to get the full breakdown."
  />

  {#if notes}
    <DashedNote label="Your notes">
      <p class="m-0 text-text0 whitespace-pre-wrap">{notes}</p>
    </DashedNote>
  {/if}
</div>
