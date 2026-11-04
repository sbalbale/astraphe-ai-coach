<script lang="ts">
  /**
   * Calendar mark for a session's state (design: Plan · link a workout legend):
   * linked = filled green tick, done without a workout = green ring tick, missed = dashed ring.
   */
  import type { DayMark } from '$lib/utils/linking';

  let { mark, size = 16 }: { mark: DayMark; size?: number } = $props();

  const label = $derived(mark === 'linked' ? 'Done, linked' : mark === 'mark' ? 'Done, no workout' : mark === 'missed' ? 'Missed' : '');
</script>

{#if mark === 'linked'}
  <span role="img" aria-label={label} class="inline-flex shrink-0 items-center justify-center rounded-full bg-green text-on-accent" style="width: {size}px; height: {size}px">
    <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"></path></svg>
  </span>
{:else if mark === 'mark'}
  <span role="img" aria-label={label} class="inline-flex shrink-0 items-center justify-center rounded-full border-[1.5px] border-green text-green" style="width: {size - 2}px; height: {size - 2}px">
    <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"></path></svg>
  </span>
{:else if mark === 'missed'}
  <span role="img" aria-label={label} class="inline-block shrink-0 rounded-full border-[1.5px] border-dashed border-text2" style="width: {size - 4}px; height: {size - 4}px"></span>
{/if}
