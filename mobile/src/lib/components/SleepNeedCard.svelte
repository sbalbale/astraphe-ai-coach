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
  const label = 'font-mono text-[11px] tracking-[0.12em] uppercase';

  // Tap the card to see what each night's need is made of (zero parts included).
  let open = $state(false);
  const cols = $derived(
    [need ? { name: nightLabel, p: need } : null, tonight ? { name: 'Tonight', p: tonight } : null].filter(
      (c): c is { name: string; p: SleepNeedParts } => c !== null
    )
  );
  const rows: { k: string; v: (p: SleepNeedParts) => string }[] = [
    { k: 'Baseline', v: (p) => formatMinutes(p.baseline) },
    { k: 'Strain', v: (p) => `+${formatMinutes(p.strain)}` },
    { k: 'Carried debt', v: (p) => `+${formatMinutes(p.debt)}` },
    { k: 'Total', v: (p) => formatMinutes(p.total) }
  ];
</script>

<section
  aria-label="Sleep need"
  class={inset
    ? 'flex flex-col px-3.5 py-3 rounded-[14px] bg-bg1'
    : 'bg-bg2 border border-border rounded-[24px] px-[18px] py-4 flex flex-col'}
>
  <button
    type="button"
    class="flex flex-col gap-3 p-0 border-0 bg-transparent text-left text-text0 cursor-pointer"
    aria-expanded={open}
    aria-controls="sleep-need-breakdown"
    onclick={() => (open = !open)}
  >
    <span class="flex items-center gap-1.5">
      <span class="font-display font-normal {inset ? 'text-[18px]' : 'text-[22px]'}">Sleep need</span>
      <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" class="text-text2 transition-transform {open ? 'rotate-180' : ''}"><path d="m6 9 6 6 6-6"></path></svg>
    </span>

    <span class="grid gap-4 {need && tonight ? 'grid-cols-[minmax(0,1fr)_auto]' : 'grid-cols-1'}">
      {#if need}
        <span class="flex flex-col gap-1.5 min-w-0">
          <span class="{label} text-text2">{nightLabel}</span>
          <span class="flex items-baseline gap-1.5 flex-wrap">
            <span class="text-[20px] font-medium leading-none whitespace-nowrap">{formatMinutes(slept)}</span>
            <span class="text-[12px] text-text2 whitespace-nowrap">of {formatMinutes(need.total)}</span>
          </span>
          <span
            role="progressbar"
            aria-label="{nightLabel}: sleep need met"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow={Math.min(100, pct ?? 0)}
            class="block h-1.5 rounded-full bg-bg3 overflow-hidden"
          >
            <span class="block h-full rounded-full" style="width: {Math.min(100, pct ?? 0)}%; background: {boundedScoreCssColor(Math.min(100, pct ?? 0))}"></span>
          </span>
          <span class="text-[12px] text-text2">{pct}% met{napMin > 0 ? ` · ${formatMinutes(napMin)} nap` : ''}</span>
        </span>
      {/if}
      {#if tonight}
        <span class="flex flex-col gap-1.5 {need ? 'pl-5 pr-1 border-l border-border' : ''}">
          <span class="{label} text-blue">Tonight</span>
          <span class="text-[20px] font-medium leading-none whitespace-nowrap">{formatMinutes(tonight.total)}</span>
        </span>
      {/if}
    </span>
  </button>

  {#if open}
    <table id="sleep-need-breakdown" class="mt-3 pt-3 border-t border-border w-full text-[13px] border-collapse">
      {#if cols.length > 1}
        <thead>
          <tr>
            <th class="sr-only">Part</th>
            {#each cols as c (c.name)}
              <th scope="col" class="{label} font-normal text-right pb-1.5 {c.name === 'Tonight' ? 'text-blue' : 'text-text2'}">{c.name}</th>
            {/each}
          </tr>
        </thead>
      {/if}
      <tbody>
        {#each rows as r (r.k)}
          <tr class={r.k === 'Total' ? 'border-t border-border' : ''}>
            <th scope="row" class="text-left font-normal py-1 {r.k === 'Total' ? 'text-text0 pt-2' : 'text-text2'}">{r.k}</th>
            {#each cols as c (c.name)}
              <td class="text-right py-1 font-mono {r.k === 'Total' ? 'text-text0 pt-2' : 'text-text1'}">{r.v(c.p)}</td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
    {#if tonight}
      <p class="m-0 mt-2 text-[11px] leading-[1.45] text-text2">
        Tonight's need rises if you train later today. Carried debt is 80% of the sleep you were short the night before.
      </p>
    {/if}
  {/if}
</section>
