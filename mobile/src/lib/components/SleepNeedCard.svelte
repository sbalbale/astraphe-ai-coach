<script lang="ts">
  /**
   * Sleep need for a night: the total, what made it up (baseline, strain, carried debt),
   * and how much of it was slept. On today it also shows tonight's estimate.
   */
  import { boundedScoreCssColor } from '$lib/scoreColors';
  import type { SleepNeedParts } from '$lib/utils/sleepNeed';

  let {
    need,
    asleepMin,
    napMin = 0,
    tonight = null,
    inset = false
  }: {
    /** The need for the selected night, or null when none was stored. */
    need: SleepNeedParts | null;
    /** Time asleep that night (the main sleep, without naps). */
    asleepMin: number;
    /** Nap sleep that day: not part of the night, but it counts toward the need. */
    napMin?: number;
    tonight?: SleepNeedParts | null;
    /** Inside another card (wide Summary) rather than a card of its own. */
    inset?: boolean;
  } = $props();

  /** "8h", "36m", "8h 48m". */
  function formatMinutes(mins: number): string {
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    return h && m % 60 ? `${h}h ${m % 60}m` : h ? `${h}h` : `${m}m`;
  }

  const pct = $derived(need && need.total > 0 ? Math.round(((asleepMin + napMin) / need.total) * 100) : null);
  /** "8h base · +15m strain · +1h 15m debt", leaving out parts that add nothing. */
  const breakdown = (p: SleepNeedParts) =>
    [
      `${formatMinutes(p.baseline)} base`,
      p.strain > 0 ? `+${formatMinutes(p.strain)} strain` : '',
      p.debt > 0 ? `+${formatMinutes(p.debt)} carried debt` : ''
    ]
      .filter(Boolean)
      .join(' · ');
</script>

<section
  aria-label="Sleep need"
  class={inset
    ? 'flex flex-col gap-2.5 px-3.5 py-3 rounded-[14px] bg-bg1'
    : 'bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-2.5'}
>
  {#if need}
    <div class="flex justify-between items-baseline gap-3">
      <h2 class="m-0 font-display font-normal {inset ? 'text-[18px]' : 'text-[22px]'}">Sleep need</h2>
      <span class="text-[22px] font-medium leading-none whitespace-nowrap">{formatMinutes(need.total)}</span>
    </div>
    <div
      role="progressbar"
      aria-label="Sleep need met"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={Math.min(100, pct ?? 0)}
      class="h-1.5 rounded-full bg-bg3 overflow-hidden"
    >
      <span class="block h-full rounded-full" style="width: {Math.min(100, pct ?? 0)}%; background: {boundedScoreCssColor(Math.min(100, pct ?? 0))}"></span>
    </div>
    <div class="flex justify-between items-baseline gap-3 text-[12px] text-text2">
      <span>{formatMinutes(asleepMin)} asleep{napMin > 0 ? ` + ${formatMinutes(napMin)} nap` : ''}</span>
      {#if pct !== null}<span class="font-mono text-text1">{pct}%</span>{/if}
    </div>
    <span class="font-mono text-[11px] text-text2">{breakdown(need)}</span>
  {/if}
  {#if tonight}
    <div
      class="flex justify-between items-baseline gap-3 {need ? 'pt-2.5 border-t border-border' : ''}"
      title={breakdown(tonight)}
    >
      <span class="font-mono text-[11px] tracking-[0.12em] text-blue">TONIGHT</span>
      <span class="text-[17px] font-medium whitespace-nowrap">{formatMinutes(tonight.total)}</span>
    </div>
  {/if}
</section>
