<script lang="ts">
  /**
   * Night plus naps for a day that has a nap. Naps aren't part of the night's time asleep
   * or score, so this is the one place the day's whole sleep is added up.
   */
  let {
    nightMin,
    napMin,
    napCount,
    inset = false
  }: {
    nightMin: number;
    napMin: number;
    napCount: number;
    /** Inside another card (wide Summary) rather than a card of its own. */
    inset?: boolean;
  } = $props();

  function formatMinutes(mins: number): string {
    const m = Math.max(0, Math.round(mins));
    const h = Math.floor(m / 60);
    return h && m % 60 ? `${h}h ${m % 60}m` : h ? `${h}h` : `${m}m`;
  }
</script>

<section
  aria-label="Total time asleep"
  class={inset
    ? 'flex flex-col gap-1 px-3.5 py-3 rounded-[14px] bg-bg1'
    : 'bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col gap-1'}
>
  <div class="flex justify-between items-baseline gap-3">
    <h2 class="m-0 font-display font-normal {inset ? 'text-[18px]' : 'text-[22px]'}">Total asleep</h2>
    <span class="text-[22px] font-medium leading-none whitespace-nowrap">{formatMinutes(nightMin + napMin)}</span>
  </div>
  <span class="text-[12px] text-text2">
    {formatMinutes(nightMin)} night + {formatMinutes(napMin)} {napCount > 1 ? `in ${napCount} naps` : 'nap'}
  </span>
</section>
