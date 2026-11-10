<script lang="ts">
  /**
   * Wide Body view, Strain (design: WBody): what built the day's strain (workouts, then
   * wearable all-day activity), load balance for the day, and strain over the last 7 days.
   */
  import { format, parseISO } from 'date-fns';
  import { formCssColor } from '$lib/scoreColors';
  import { workoutMeta, type DayStrain } from '$lib/utils/bodyWide';

  type Day = { date: string; score: number };
  let {
    day,
    strain,
    ctl,
    atl,
    tsb,
    days,
    selected,
    onSelect
  }: {
    day: string;
    strain: DayStrain;
    ctl: number | null;
    atl: number | null;
    tsb: number | null;
    days: Day[];
    selected: number;
    onSelect: (i: number) => void;
  } = $props();

  const isToday = $derived(day === format(new Date(), 'yyyy-MM-dd'));
  const heading = $derived(isToday ? "What built today's strain" : `What built ${format(parseISO(day), 'EEEE')}'s strain`);
  /** Bar segments as % of the 0–100 scale, in list order: each workout, then activity. */
  const barSegments = $derived(
    [
      ...strain.workouts.map((p) => ({ kind: 'workout' as const, pct: p.value })),
      { kind: 'activity' as const, pct: strain.activity }
    ].filter((s) => s.pct > 0)
  );
  const maxDay = $derived(Math.max(100, ...days.map((d) => d.score)));

  function share(v: number): number {
    return strain.score > 0 ? Math.max(2, Math.min(100, Math.round((v / strain.score) * 100))) : 0;
  }
  function fmt1(v: number | null): string {
    return v === null ? '--' : v.toFixed(1);
  }
</script>

<div class="flex-1 min-h-0 grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-4">
  <section aria-label="Contributing" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
    <div class="flex justify-between items-baseline">
      <h2 class="m-0 font-display font-normal text-[26px]">{heading}</h2>
      <span class="font-mono text-[11px] text-text2">{strain.score} / 100</span>
    </div>
    <!-- One segment per row below (workouts, then daily activity), on the 0-100 scale.
         The track clips the left end; only the last filled segment rounds its right end,
         so segments meet flush with a hairline gap instead of rounded caps overlapping. -->
    <div class="relative h-3.5 rounded-[7px] bg-border overflow-hidden flex gap-[2px]" aria-hidden="true">
      {#each barSegments as seg, i (i)}
        <span
          class="h-full shrink-0 {seg.kind === 'activity' ? 'bg-steel' : 'bg-blue'} {i === barSegments.length - 1 ? 'rounded-r-[7px]' : ''}"
          style="width: {seg.pct}%"
        ></span>
      {/each}
    </div>
    {#if strain.workouts.length === 0 && strain.activity === 0}
      <p class="m-0 text-[13px] text-text2">No workouts or all-day activity recorded for this day.</p>
    {/if}
    {#each strain.workouts as p (p.workout.id ?? p.workout.started_at)}
      <a
        href="/training?workout_id={encodeURIComponent(String(p.workout.id))}"
        class="flex flex-col gap-2 px-4 py-3.5 rounded-2xl bg-bg1 border border-rail-border no-underline text-text0 hover:border-popover-border"
      >
        <span class="flex justify-between gap-3"><span class="text-[14px] font-medium truncate">{p.workout.title || 'Workout'}</span><span class="font-mono text-[14px] text-blue">+{p.value}</span></span>
        <span aria-hidden="true" class="h-1.5 rounded-[3px] bg-border"><span class="block h-1.5 rounded-[3px] bg-blue" style="width: {share(p.value)}%"></span></span>
        <span class="text-[12px] text-text2">{[workoutMeta(p.workout), 'open workout'].filter(Boolean).join(' · ')}</span>
      </a>
    {/each}
    {#if strain.activity > 0}
      <div class="flex flex-col gap-2 px-4 py-3.5 rounded-2xl bg-bg1 border border-rail-border">
        <span class="flex justify-between"><span class="text-[14px] font-medium">Daily activity</span><span class="font-mono text-[14px] text-text1">+{strain.activity}</span></span>
        <span aria-hidden="true" class="h-1.5 rounded-[3px] bg-border"><span class="block h-1.5 rounded-[3px] bg-steel" style="width: {share(strain.activity)}%"></span></span>
        <span class="text-[12px] text-text2">Time active outside workouts, from your all-day heart rate</span>
      </div>
    {/if}
  </section>

  <section aria-label="Load balance" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
    <h2 class="m-0 font-display font-normal text-[26px]">Load balance</h2>
    <dl class="m-0 grid grid-cols-3 gap-2">
      <div class="p-3 rounded-[14px] bg-bg1 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fitness</dt><dd class="m-0 text-[20px] font-medium">{fmt1(ctl)}</dd></div>
      <div class="p-3 rounded-[14px] bg-bg1 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fatigue</dt><dd class="m-0 text-[20px] font-medium">{fmt1(atl)}</dd></div>
      <div class="p-3 rounded-[14px] bg-bg1 flex flex-col-reverse gap-0.5">
        <dt class="text-[11px] text-text2">Form</dt>
        <dd class="m-0 text-[20px] font-medium" style={tsb === null ? '' : `color: ${formCssColor(tsb)}`}>{tsb === null ? '--' : `${tsb > 0 ? '+' : ''}${tsb.toFixed(1)}`}</dd>
      </div>
    </dl>
    <span class="font-mono text-[10px] tracking-[0.14em] text-text2">STRAIN · LAST 7 DAYS</span>
    <div class="flex-1 min-h-[110px] flex items-end gap-2">
      {#each days as d, i (d.date)}
        {@const on = i === selected}
        <button
          type="button"
          class="flex-1 h-full p-0 border-0 bg-transparent cursor-pointer flex flex-col justify-end items-stretch gap-1.5"
          aria-label="{format(parseISO(d.date), 'EEE d MMM')}: strain {d.score}"
          aria-pressed={on}
          onclick={() => onSelect(i)}
        >
          <span class="font-mono text-[10px] text-center {on ? 'text-text0' : 'text-text1'}">{d.score > 0 ? d.score : '--'}</span>
          <span aria-hidden="true" class="block rounded-md {on ? 'bg-blue' : 'bg-popover-border'}" style="height: {d.score > 0 ? Math.max(4, Math.round((d.score / maxDay) * 100)) : 2}%"></span>
          <span class="font-mono text-[10px] text-center uppercase {on ? 'text-text0' : 'text-text2'}">{format(parseISO(d.date), 'EEEEE')}</span>
        </button>
      {/each}
    </div>
    <a href="/trends" class="text-[13px] text-blue no-underline">See fitness and fatigue trends</a>
  </section>
</div>
