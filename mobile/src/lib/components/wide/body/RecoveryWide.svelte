<script lang="ts">
  /**
   * Wide Body view, Recovery (design: WBody): drivers against the 14-day normal band, and
   * the 7-day recovery trend with a "why" line for the picked day.
   */
  import { format, parseISO } from 'date-fns';
  import { boundedScoreCssColor } from '$lib/scoreColors';
  import { baselineBefore, finite, recoveryWhy, seriesWindow, sparkline } from '$lib/utils/bodyWide';

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

  type Driver = {
    name: string;
    value: string;
    delta: string;
    tone: 'good' | 'bad' | 'neutral';
    accent: boolean;
    spark: ReturnType<typeof sparkline>;
  };

  /** Skin temperature deviation (°C): Garmin gives it directly, else vs the 7 days before. */
  const skinDevC = $derived.by(() => {
    const dev = finite(row?.skin_temp_deviation_c);
    if (dev !== null) return dev;
    const t = finite(row?.skin_temp);
    const base = baselineBefore(series, day, 'skin_temp');
    return t !== null && base !== null ? t - base : null;
  });

  const drivers = $derived.by<Driver[]>(() => {
    const out: Driver[] = [];
    const hrv = pos(row?.hrv_rmssd);
    if (hrv !== null) {
      const base = baselineBefore(series, day, 'hrv_rmssd');
      const pct = base !== null ? Math.round(((hrv - base) / base) * 100) : null;
      out.push({
        name: 'HRV',
        value: `${Math.round(hrv)} ms`,
        delta: pct === null ? '' : Math.abs(pct) < 1 ? 'at baseline' : `${pct > 0 ? '↑' : '↓'} ${Math.abs(pct)}%`,
        tone: pct === null || Math.abs(pct) < 3 ? 'neutral' : pct > 0 ? 'good' : 'bad',
        accent: true,
        spark: sparkline(seriesWindow(series, day, 'hrv_rmssd'))
      });
    }
    const rhr = pos(row?.resting_hr);
    if (rhr !== null) {
      const base = baselineBefore(series, day, 'resting_hr');
      const d = base !== null ? Math.round(rhr - base) : null;
      out.push({
        name: 'Resting HR',
        value: `${Math.round(rhr)} bpm`,
        delta: d === null ? '' : d === 0 ? 'steady' : `${d > 0 ? '↑' : '↓'} ${Math.abs(d)} bpm`,
        tone: d === null || d === 0 ? 'neutral' : d < 0 ? 'good' : 'bad',
        accent: false,
        spark: sparkline(seriesWindow(series, day, 'resting_hr'))
      });
    }
    const sleep = pos(row?.sleep_score);
    if (sleep !== null) {
      const base = baselineBefore(series, day, 'sleep_score');
      const d = base !== null ? Math.round(sleep - base) : null;
      out.push({
        name: 'Sleep score',
        value: String(Math.round(sleep)),
        delta: d === null ? '' : d === 0 ? 'steady' : `${d > 0 ? '↑' : '↓'} ${Math.abs(d)}`,
        tone: d === null || Math.abs(d) < 2 ? 'neutral' : d > 0 ? 'good' : 'bad',
        accent: false,
        spark: sparkline(seriesWindow(series, day, 'sleep_score'))
      });
    }
    if (skinDevC !== null) {
      const shown = isImperial ? (skinDevC * 9) / 5 : skinDevC;
      const r = Math.round(shown * 10) / 10;
      const field = series.some((x) => finite(x?.skin_temp_deviation_c) !== null) ? 'skin_temp_deviation_c' : 'skin_temp';
      const abnormal = Math.abs(skinDevC) >= 0.5;
      out.push({
        name: 'Skin temp',
        value: `${r > 0 ? '+' : ''}${r.toFixed(1)}°${isImperial ? 'F' : ''}`,
        delta: abnormal ? (skinDevC > 0 ? 'raised' : 'low') : 'normal',
        tone: abnormal ? 'bad' : 'neutral',
        accent: false,
        spark: sparkline(seriesWindow(series, day, field))
      });
    }
    const spo2 = pos(row?.spo2_pct);
    if (spo2 !== null) {
      const base = baselineBefore(series, day, 'spo2_pct');
      // Low when under 95% or 2+ points below your usual night.
      const low = spo2 < 95 || (base !== null && base - spo2 >= 2);
      out.push({
        name: 'SpO2',
        value: `${Math.round(spo2)}%`,
        delta: low ? 'low' : 'normal',
        tone: low ? 'bad' : 'neutral',
        accent: false,
        spark: sparkline(seriesWindow(series, day, 'spo2_pct'))
      });
    }
    return out;
  });

  const sel = $derived(days[selected]);
  const readout = $derived(
    sel ? `${format(parseISO(sel.date), 'EEE d MMM').toUpperCase()} · ${sel.missing ? 'NO SCORE' : `${Math.round(sel.score)}%`}` : ''
  );
  const why = $derived(sel ? recoveryWhy(series, sel.date) : null);

  const toneClass = { good: 'text-green', bad: 'text-amber', neutral: 'text-text2' };
</script>

<div class="flex-1 min-h-0 grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-4">
  <section aria-label="vs your baseline" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col">
    <div class="flex justify-between items-baseline pb-2.5">
      <h2 class="m-0 font-display font-normal text-[26px]">vs your baseline</h2>
      <span class="font-mono text-[11px] text-text2">14 DAYS · BAND = NORMAL</span>
    </div>
    {#if drivers.length === 0}
      <p class="m-0 py-4 border-t border-rail-border text-[13px] text-text2">No HRV, resting HR or sleep readings for this day.</p>
    {/if}
    {#each drivers as dr (dr.name)}
      <div class="grid grid-cols-[1fr_minmax(120px,220px)_70px] gap-4 items-center py-3.5 border-t border-rail-border">
        <span class="flex flex-col gap-0.5"><span class="text-[12px] text-text2">{dr.name}</span><span class="text-[18px] font-medium">{dr.value}</span></span>
        {#if dr.spark}
          <svg width="100%" height="40" viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true" class="block">
            <rect x="0" y={dr.spark.bandY} width="200" height={dr.spark.bandH} rx="4" fill="currentColor" class="text-glass2"></rect>
            <polyline points={dr.spark.points} fill="none" stroke={dr.accent ? 'var(--blue)' : 'var(--text1)'} stroke-width="1.8" stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>
          </svg>
        {:else}
          <span class="text-[11px] text-text3">Not enough history</span>
        {/if}
        <span class="text-right text-[13px] {toneClass[dr.tone]}">{dr.delta}</span>
      </div>
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
