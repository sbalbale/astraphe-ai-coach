<script lang="ts">
  /**
   * Sleep need, split so the two numbers can't be mistaken for each other: the selected
   * night (what was slept against what it needed) and, on today, tonight's target with
   * what it is made of. Past days show only their night.
   */
  import { boundedScoreCssColor } from '$lib/scoreColors';
  import type { SleepNeedParts } from '$lib/utils/sleepNeed';

  let {
    need,
    asleepMin,
    napMin = 0,
    tonight = null,
    nightLabel = 'Last night',
    inset = false
  }: {
    /** The need for the selected night, or null when none was stored. */
    need: SleepNeedParts | null;
    /** Time asleep that night (the main sleep, without naps). */
    asleepMin: number;
    /** Nap sleep that day: not part of the night, but it counts toward the need. */
    napMin?: number;
    tonight?: SleepNeedParts | null;
    /** "Last night" on today, "Sun → Mon" on a past day. */
    nightLabel?: string;
    /** Inside another card (wide Summary) rather than a card of its own. */
    inset?: boolean;
  } = $props();

  /** "8h", "36m", "8h 48m". */
  function formatMinutes(mins: number): string {
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    return h && m % 60 ? `${h}h ${m % 60}m` : h ? `${h}h` : `${m}m`;
  }

  const slept = $derived(asleepMin + napMin);
  const pct = $derived(need && need.total > 0 ? Math.round((slept / need.total) * 100) : null);
  /** "8h base · +15m strain · +1h 15m carried debt", leaving out parts that add nothing. */
  const breakdown = (p: SleepNeedParts) =>
    [
      `${formatMinutes(p.baseline)} base`,
      p.strain > 0 ? `+${formatMinutes(p.strain)} strain` : '',
      p.debt > 0 ? `+${formatMinutes(p.debt)} carried debt` : ''
    ]
      .filter(Boolean)
      .join(' · ');
  const label = 'font-mono text-[11px] tracking-[0.12em] uppercase';
</script>

<section
  aria-label="Sleep need"
  class={inset
    ? 'flex flex-col gap-3 px-3.5 py-3 rounded-[14px] bg-bg1'
    : 'bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-3'}
>
  <h2 class="m-0 font-display font-normal {inset ? 'text-[18px]' : 'text-[22px]'}">Sleep need</h2>

  <div class="grid gap-4 {need && tonight ? 'grid-cols-2' : 'grid-cols-1'}">
    {#if need}
      <div class="flex flex-col gap-1.5 min-w-0">
        <span class="{label} text-text2">{nightLabel}</span>
        <span class="flex items-baseline gap-1.5 flex-wrap">
          <span class="text-[20px] font-medium leading-none whitespace-nowrap">{formatMinutes(slept)}</span>
          <span class="text-[12px] text-text2 whitespace-nowrap">of {formatMinutes(need.total)}</span>
        </span>
        <div
          role="progressbar"
          aria-label="{nightLabel}: sleep need met"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow={Math.min(100, pct ?? 0)}
          class="h-1.5 rounded-full bg-bg3 overflow-hidden"
        >
          <span class="block h-full rounded-full" style="width: {Math.min(100, pct ?? 0)}%; background: {boundedScoreCssColor(Math.min(100, pct ?? 0))}"></span>
        </div>
        <span class="text-[12px] text-text2">
          {pct}% met{napMin > 0 ? ` · ${formatMinutes(napMin)} nap` : ''}
        </span>
        {#if !tonight}
          <span class="font-mono text-[11px] text-text2">{breakdown(need)}</span>
        {/if}
      </div>
    {/if}
    {#if tonight}
      <div class="flex flex-col gap-1.5 min-w-0 {need ? 'pl-4 border-l border-border' : ''}">
        <span class="{label} text-blue">Tonight</span>
        <span class="text-[20px] font-medium leading-none whitespace-nowrap">{formatMinutes(tonight.total)}</span>
        <span class="text-[12px] text-text2 leading-[1.45]">{breakdown(tonight)}{tonight.strain > 0 ? ' so far' : ''}</span>
      </div>
    {/if}
  </div>
</section>
