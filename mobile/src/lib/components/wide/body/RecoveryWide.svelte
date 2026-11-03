<script lang="ts">
  /**
   * Wide Body view, Recovery (design: WBody): drivers against the 14-day normal band, and
   * the 7-day recovery trend with a "why" line for the picked day.
   */
  import { format, parseISO } from 'date-fns';
  import { boundedScoreCssColor, zScoreCssColor } from '$lib/scoreColors';
  import BaselineBar from '$lib/components/BaselineBar.svelte';
  import { baselineBefore, finite, recoveryWhy } from '$lib/utils/bodyWide';

  type Day = { date: string; score: number; missing: boolean };
  let {
    series,
    day,
    row,
    days,
    selected,
    onSelect,
    isImperial = false
  }: {
    series: Record<string, any>[];
    /** The picked day (YYYY-MM-DD). */
    day: string;
    /** That day's row (today may carry last night's forward); null when missing. */
    row: Record<string, any> | null;
    /** The 7-day window, oldest first. */
    days: Day[];
    selected: number;
    onSelect: (i: number) => void;
    isImperial?: boolean;
  } = $props();

  function pos(v: unknown): number | null {
    const n = finite(v);
    return n !== null && n > 0 ? n : null;
  }

  type Driver = { name: string; value: string; delta: string; z: number | null; color: string };

  const signed = (n: number) => `${n > 0 ? '+' : ''}${n}`;

  /** Skin temperature deviation (°C): Garmin gives it directly, else vs the 7 days before. */
  const skinDevC = $derived.by(() => {
    const dev = finite(row?.skin_temp_deviation_c);
    if (dev !== null) return dev;
    const t = finite(row?.skin_temp);
    const base = baselineBefore(series, day, 'skin_temp');
    return t !== null && base !== null ? t - base : null;
  });

  /** Same rows as the phone Recovery card (bar + dot vs the 7-day baseline), plus skin temp and SpO2. */
  const drivers = $derived.by<Driver[]>(() => {
    const out: Driver[] = [];
    const z = (v: unknown) => finite(v);

    const hrv = pos(row?.hrv_rmssd);
    if (hrv !== null) {
      const base = baselineBefore(series, day, 'hrv_rmssd');
      const hz = z(row?.hrv_z);
      out.push({
        name: 'HRV',
        value: `${Math.round(hrv)} ms`,
        delta: base !== null ? signed(Math.round(hrv - base)) : '',
        z: hz,
        color: hz === null ? 'var(--text2)' : zScoreCssColor(hz)
      });
    }
    const rhr = pos(row?.resting_hr);
    if (rhr !== null) {
      const base = baselineBefore(series, day, 'resting_hr');
      const rz = z(row?.rhr_z);
      out.push({
        name: 'Resting HR',
        value: `${Math.round(rhr)} bpm`,
        delta: base !== null ? signed(Math.round(rhr - base)) : '',
        z: rz,
        color: rz === null ? 'var(--text2)' : zScoreCssColor(rz, true)
      });
    }
    const sleep = pos(row?.sleep_score);
    if (sleep !== null) {
      const base = baselineBefore(series, day, 'sleep_score');
      const d = base !== null ? Math.round(sleep - base) : null;
      const sz = d === null ? null : d / 8;
      out.push({
        name: 'Sleep',
        value: `${Math.round(sleep)}%`,
        delta: d === null ? '' : signed(d),
        z: sz,
        color: sz === null ? 'var(--text2)' : zScoreCssColor(sz)
      });
    }
    if (skinDevC !== null) {
      const shown = isImperial ? (skinDevC * 9) / 5 : skinDevC;
      const r = Math.round(shown * 10) / 10;
      // Off in either direction matters; 0.5 °C ≈ one step.
      const step = skinDevC / 0.5;
      out.push({
        name: 'Skin temp',
        value: `${r > 0 ? '+' : ''}${r.toFixed(1)}°${isImperial ? 'F' : 'C'}`,
        delta: Math.abs(skinDevC) >= 0.5 ? (skinDevC > 0 ? 'raised' : 'low') : 'normal',
        z: step,
        color: zScoreCssColor(-Math.abs(step))
      });
    }
    const spo2 = pos(row?.spo2_pct);
    if (spo2 !== null) {
      const base = baselineBefore(series, day, 'spo2_pct');
      const d = base !== null ? Math.round(spo2 - base) : null;
      // Low when under 95% or 2+ points below your usual night.
      const low = spo2 < 95 || (d !== null && d <= -2);
      out.push({
        name: 'SpO2',
        value: `${Math.round(spo2)}%`,
        delta: d === null ? (low ? 'low' : '') : signed(d),
        z: d === null ? null : d / 1.5,
        color: low ? (spo2 < 92 ? 'var(--red)' : 'var(--amber)') : 'var(--teal)'
      });
    }
    return out;
  });

  const sel = $derived(days[selected]);
  const readout = $derived(
    sel ? `${format(parseISO(sel.date), 'EEE d MMM').toUpperCase()} · ${sel.missing ? 'NO SCORE' : `${Math.round(sel.score)}%`}` : ''
  );
  const why = $derived(sel ? recoveryWhy(series, sel.date) : null);

</script>

<div class="flex-1 min-h-0 grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-4">
  <section aria-label="vs your baseline" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col">
    <div class="flex justify-between items-baseline pb-2.5">
      <h2 class="m-0 font-display font-normal text-[26px]">vs your baseline</h2>
      <span class="font-mono text-[11px] text-text2">7-DAY</span>
    </div>
    {#if drivers.length === 0}
      <p class="m-0 py-4 border-t border-rail-border text-[13px] text-text2">No HRV, resting HR or sleep readings for this day.</p>
    {/if}
    {#each drivers as dr (dr.name)}
      <BaselineBar name={dr.name} value={dr.value} delta={dr.delta} z={dr.z} color={dr.color} labelWidth={110} valueWidth={90} size="lg" />
    {/each}
  </section>

  <section aria-label="Recovery, last 7 days" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
    <div class="flex justify-between items-baseline">
      <h2 class="m-0 font-display font-normal text-[26px]">7-day trend</h2>
      <span aria-live="polite" class="font-mono text-[11px] text-text1">{readout}</span>
    </div>
    <div class="flex-1 min-h-[160px] flex items-end gap-2.5">
      {#each days as d, i (d.date)}
        {@const on = i === selected}
        <button
          type="button"
          class="group flex-1 h-full p-0 border-0 bg-transparent cursor-pointer flex flex-col justify-end items-stretch gap-2"
          aria-label="{format(parseISO(d.date), 'EEE d MMM')}: {d.missing ? 'no recovery score' : `recovery ${Math.round(d.score)}%`}"
          aria-pressed={on}
          onclick={() => onSelect(i)}
        >
          <span class="font-mono text-[11px] text-center {on ? 'text-text0' : 'text-text2'}">{d.missing ? '--' : `${Math.round(d.score)}%`}</span>
          {#if d.missing}
            <span aria-hidden="true" class="block h-[18%] rounded-lg border border-dashed {on ? 'border-text2' : 'border-popover-border'}"></span>
          {:else}
            <span
              aria-hidden="true"
              class="block rounded-lg transition-opacity group-hover:opacity-100 {on ? 'opacity-100' : 'opacity-40'}"
              style="height: {Math.max(4, Math.min(100, d.score))}%; background: {boundedScoreCssColor(d.score)}"
            ></span>
          {/if}
          <span class="font-mono text-[10px] text-text2 text-center uppercase">{format(parseISO(d.date), 'EEE')}</span>
        </button>
      {/each}
    </div>
    {#if why}
      <div class="flex gap-3 items-start px-3.5 py-3 rounded-[14px] bg-bg1 border border-dashed border-popover-border">
        <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">WHY</span>
        <span class="text-[13px] leading-[1.45] text-text0/85">{why}</span>
      </div>
    {/if}
    <a href="/readiness" class="text-[13px] text-blue no-underline">How recovery feeds today's readiness</a>
  </section>
</div>
