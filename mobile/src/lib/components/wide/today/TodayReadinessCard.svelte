<script lang="ts">
  /** Wide Today: readiness score + recovery / HRV / sleep / form (design: WToday, WTodayPortrait). */
  import { resolve } from '$app/paths';
  import { readinessStatus } from './todayWide';

  let {
    score,
    recovery,
    hrv,
    sleepLabel,
    form,
    stale = false,
    notes = [],
    vertical = false
  }: {
    score: number | null;
    recovery: number | null;
    hrv: number | null;
    sleepLabel: string | null;
    form: number | null;
    stale?: boolean;
    notes?: string[];
    /** Portrait: stacked, fixed 420 px tall next to the coach card. */
    vertical?: boolean;
  } = $props();

  const status = $derived(readinessStatus(score));
  const toneClass = $derived(
    { green: 'text-green', amber: 'text-amber', red: 'text-red', muted: 'text-text2' }[status.tone]
  );
  const formLabel = $derived(form === null ? '--' : form > 0 ? `+${form.toFixed(1)}` : form.toFixed(1));
  const stats = $derived([
    { label: 'Recovery', value: recovery === null ? '--' : `${Math.round(recovery)}%` },
    { label: 'HRV', value: hrv === null ? '--' : `${Math.round(hrv)} ms` },
    { label: 'Sleep', value: sleepLabel ?? '--' },
    { label: 'Form', value: formLabel }
  ]);
  const aria = $derived(
    score === null ? 'Readiness: no data. Open readiness details' : `Readiness ${score}, ${status.label.toLowerCase()}. Open readiness details`
  );
</script>

<a
  href={resolve('/readiness')}
  aria-label={aria}
  class="bg-bg2 border border-border rounded-[24px] p-[22px] flex text-text0 no-underline hover:border-popover-border transition-colors {vertical
    ? 'flex-col gap-[18px] items-stretch h-[420px] box-border'
    : 'gap-5 items-center'}"
>
  <span class="flex flex-col gap-0.5 min-w-[104px]">
    <span class="font-mono text-[11px] tracking-[0.14em] text-text2">READINESS</span>
    <span class="font-display text-[68px] leading-none {score === null || stale ? 'text-text2' : 'text-text0'}">{score === null ? '--' : score}</span>
    <span class="text-[13px] {toneClass}">{status.label}</span>
  </span>
  <span class="grid grid-cols-2 {vertical ? 'gap-4' : 'flex-1 gap-3'}">
    {#each stats as s (s.label)}
      <span>
        <span class="block text-[11px] text-text2">{s.label}</span>
        <span class="text-[16px] font-medium">{s.value}</span>
      </span>
    {/each}
  </span>
  {#if notes.length && vertical}
    <span class="mt-auto flex flex-col gap-1 font-mono text-[10px] text-text2">
      {#each notes as n (n)}<span>{n}</span>{/each}
    </span>
  {/if}
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="flex-none text-text3 {vertical ? 'self-end' : ''}"><path d="m9 6 6 6-6 6"></path></svg>
</a>
{#if notes.length && !vertical}
  <p class="-mt-3 m-0 px-1 flex flex-wrap gap-x-3 font-mono text-[10px] text-text2">
    {#each notes as n (n)}<span>{n}</span>{/each}
  </p>
{/if}
