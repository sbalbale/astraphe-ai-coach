<script lang="ts">
  /** Phone Today: one planned session (the day's key session, or another session that day). */
  import { resolve } from '$app/paths';
  import type { Workout } from '$lib/types/training';
  import { profileBars, workPctFtp, workWattRange } from '$lib/components/wide/today/todayWide';
  import { sessionNotesSummary } from '$lib/utils/sessionNotes';

  let {
    workout,
    ftp,
    label,
    provisional = false
  }: {
    workout: Workout;
    ftp: number;
    /** Eyebrow, e.g. "Key session" or "Also today". */
    label: string;
    provisional?: boolean;
  } = $props();

  const ZONE_LABEL: Record<string, string> = {
    Recovery: 'Z1',
    Endurance: 'Z2',
    Tempo: 'Z3–Z4',
    Threshold: 'Z4',
    VO2Max: 'Z5',
    Anaerobic: 'Z6'
  };

  // Same figures as the Plan session sheet: planned minutes, and the hardest step's
  // %FTP ±2.5% in watts.
  const range = $derived.by(() => {
    const watts = workWattRange(workout, ftp);
    if (watts) return { valueLabel: watts, unit: 'W', caption: `Target · ${workPctFtp(workout)}% FTP` };
    return { valueLabel: String(workout.projected_tss), unit: 'TSS', caption: 'Projected load' };
  });
  /** Same blocks as the Plan session sheet: width by duration, height by %FTP, zone colour. */
  const bars = $derived(workout.structure?.length ? profileBars(workout) : []);
  const notes = $derived(sessionNotesSummary(workout.description));
</script>

<a
  href={resolve(`/plan?session=${encodeURIComponent(workout.id)}`)}
  aria-label="Open {workout.title} in your plan"
  class="bg-bg2 border border-border rounded-[24px] p-5 flex flex-col gap-3.5 text-text0"
>
  <div class="flex justify-between items-center">
    <span class="font-mono text-[11px] tracking-[0.14em] text-blue uppercase">{label} · {workout.sport}{provisional ? ' · provisional' : ''}</span>
    <span class="flex items-center gap-1 font-mono text-[11px] text-text2">
      {ZONE_LABEL[workout.primary_zone] ?? ''}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    </span>
  </div>
  <div class="flex flex-col gap-1">
    <h2 class="m-0 font-display font-normal text-[34px] leading-[1.05]">{workout.title}</h2>
    {#if provisional}
      <p class="m-0 text-sm leading-[1.45] text-text1">
        Your coach will confirm or adjust this once recovery comes in. Training before then? Go by feel and ease off if it feels harder than it should.
      </p>
    {:else if notes}
      <p class="m-0 text-sm leading-[1.45] text-text1">{notes}</p>
    {/if}
  </div>
  <div class="grid grid-cols-2 gap-3 border-t border-border">
    <div class="flex flex-col gap-0.5 pt-2.5">
      <span class="text-[26px] font-medium tracking-[-0.02em]">{workout.duration_minutes}<span class="text-[13px] text-text2 font-normal"> min</span></span>
      <span class="text-xs text-text2">Duration</span>
    </div>
    <div class="flex flex-col gap-0.5 pt-2.5">
      <span class="text-[26px] font-medium tracking-[-0.02em]">{range.valueLabel}<span class="text-[13px] text-text2 font-normal"> {range.unit}</span></span>
      <span class="text-xs text-text2">{range.caption}</span>
    </div>
  </div>
  {#if bars.length > 0}
    <div role="img" aria-label="Workout profile" class="flex items-end gap-[3px] h-16">
      {#each bars as b, idx (idx)}
        <div
          class="rounded-[3px]"
          style="flex: {b.grow} 1 0; height: {b.pct}%; background: {b.zone > 0 ? `var(--zone-${b.zone})` : 'var(--text2)'}"
        ></div>
      {/each}
    </div>
  {/if}
</a>
