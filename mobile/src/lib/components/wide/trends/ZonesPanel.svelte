<script lang="ts">
  /** Time in zones (design: WTrends): week / month, HR or power ranges, split read-out. */
  import { format } from 'date-fns';
  import { navTo } from '$lib/nav';
  import { HR_ZONE_HEX, HR_ZONE_LABELS } from '$lib/hrZoneDisplay';
  import {
    fmtZoneTime,
    percentages,
    splitInsight,
    zoneSecondsInWindow,
    zoneWindow,
    type ZonePeriod
  } from './trendsWide';

  type HrZone = { zone: number; name?: string; min: number; max: number };

  let {
    workouts,
    hrZones,
    ftp,
    lthr,
    period = $bindable<ZonePeriod>('week'),
    offset = $bindable(0),
    today
  }: {
    workouts: Record<string, unknown>[];
    hrZones: HrZone[];
    ftp: number;
    lthr: number;
    period?: ZonePeriod;
    offset?: number;
    today: Date;
  } = $props();

  let basis = $state<'hr' | 'power'>('hr');
  const atNow = $derived(offset === 0);
  const win = $derived(zoneWindow(period, offset, today));
  const secs = $derived(zoneSecondsInWindow(workouts as never, win.start, win.end));
  const total = $derived(secs.reduce((a, b) => a + b, 0));
  const pcts = $derived(percentages(secs));

  const MON = (d: Date) => format(d, 'MMM');
  const title = $derived.by(() => {
    if (period === 'month') {
      return format(win.start, win.start.getFullYear() === today.getFullYear() ? 'MMMM' : 'MMMM yyyy');
    }
    if (atNow) return 'This week';
    if (offset === -1) return 'Last week';
    return weekRange(win.start, win.end, false);
  });
  const sub = $derived.by(() => {
    if (period === 'month') return atNow ? 'THIS MONTH · SO FAR' : String(win.start.getFullYear());
    const r = weekRange(win.start, win.end, true);
    return atNow ? `${r} · SO FAR` : r;
  });
  function weekRange(s: Date, e: Date, upper: boolean): string {
    const m = (d: Date) => (upper ? MON(d).toUpperCase() : MON(d));
    return `${s.getDate()}${s.getMonth() !== e.getMonth() ? ` ${m(s)}` : ''}–${e.getDate()} ${m(e)}`;
  }

  // Coggan power zones as % of FTP (upper bound of Z1–Z4).
  const POWER_UPPER = [0.55, 0.75, 0.9, 1.05];
  const rows = $derived(
    [...hrZones]
      .sort((a, b) => a.zone - b.zone)
      .slice(0, 5)
      .map((z) => {
        const i = z.zone - 1;
        const hr = z.max >= 500 ? `≥ ${z.min}` : z.min <= 0 ? `< ${z.max + 1} bpm` : `${z.min}–${z.max}`;
        let watts = '—';
        if (ftp) {
          const lo = z.zone > 1 ? Math.round(ftp * POWER_UPPER[z.zone - 2]) + 1 : 0;
          const hi = z.zone <= 4 ? Math.round(ftp * POWER_UPPER[z.zone - 1]) : 0;
          watts = z.zone === 1 ? `< ${hi + 1} W` : z.zone === 5 ? `≥ ${lo} W` : `${lo}–${hi} W`;
        }
        return {
          zone: z.zone,
          name: HR_ZONE_LABELS[z.zone] ?? z.name ?? '',
          color: HR_ZONE_HEX[z.zone] ?? 'var(--text2)',
          range: basis === 'hr' ? hr : watts,
          pct: pcts[i] ?? 0,
          time: fmtZoneTime(secs[i] ?? 0)
        };
      })
  );
  const insight = $derived(splitInsight(pcts, total));

  const seg = (on: boolean) =>
    `h-[30px] px-3 border-0 rounded-lg text-[12px] font-medium cursor-pointer ${on ? 'bg-border text-text0' : 'bg-transparent text-text2'}`;
</script>

<section aria-label="Time in zones" class="min-h-0 bg-bg2 border border-border rounded-[24px] px-5 py-[18px] flex flex-col gap-3.5">
  <div class="flex justify-between items-center">
    <h2 class="m-0 font-display font-normal text-[26px]">Time in zones</h2>
    <div role="tablist" aria-label="Zone basis" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
      <button type="button" role="tab" aria-selected={basis === 'hr'} class={seg(basis === 'hr')} onclick={() => (basis = 'hr')}>HR</button>
      <button type="button" role="tab" aria-selected={basis === 'power'} disabled={!ftp} title={ftp ? undefined : 'Set your FTP in Training settings'} class="{seg(basis === 'power')} disabled:opacity-40 disabled:cursor-default" onclick={() => (basis = 'power')}>Power</button>
    </div>
  </div>

  <div class="flex items-center gap-2">
    <div role="tablist" aria-label="Period" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
      <button type="button" role="tab" aria-selected={period === 'week'} class={seg(period === 'week')} onclick={() => { period = 'week'; offset = 0; }}>Week</button>
      <button type="button" role="tab" aria-selected={period === 'month'} class={seg(period === 'month')} onclick={() => { period = 'month'; offset = 0; }}>Month</button>
    </div>
    <span class="flex-1"></span>
    <button type="button" aria-label="Previous period" class="w-[34px] h-[34px] rounded-[10px] border border-border bg-bg1 text-text1 flex items-center justify-center cursor-pointer" onclick={() => (offset -= 1)}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
    </button>
    <button type="button" aria-label="Next period" disabled={atNow} class="w-[34px] h-[34px] rounded-[10px] border border-border bg-bg1 flex items-center justify-center {atNow ? 'text-text3/50 cursor-default' : 'text-text1 cursor-pointer'}" onclick={() => { if (!atNow) offset += 1; }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
    </button>
    <button type="button" disabled={atNow} class="h-[34px] px-3 rounded-[10px] text-[12px] font-semibold {atNow ? 'bg-transparent border border-border text-text3 cursor-default' : 'bg-blue border-0 text-on-accent cursor-pointer'}" onclick={() => (offset = 0)}>{period === 'month' ? 'This month' : 'This week'}</button>
  </div>

  <div class="flex flex-col gap-0.5">
    <span class="font-display text-[30px] leading-[1.1]">{title}</span>
    <span class="font-mono text-[11px] tracking-[0.1em] text-text2">{sub}</span>
  </div>

  <div aria-hidden="true" class="flex gap-[3px] h-3">
    {#if total > 0}
      {#each rows as z (z.zone)}<span class="block h-3 rounded-[3px]" style="flex: {Math.max(z.pct, 1)} 1 0; background: {z.color}"></span>{/each}
    {:else}
      <span class="block h-3 flex-1 rounded-[3px] bg-bg3"></span>
    {/if}
  </div>

  <ul class="list-none m-0 p-0 flex flex-col">
    {#each rows as z (z.zone)}
      <li class="grid grid-cols-[12px_1fr_auto_44px_58px] gap-2.5 items-center py-[11px] border-t border-rail-border text-[13px]">
        <span aria-hidden="true" class="w-2.5 h-2.5 rounded-[3px]" style="background: {z.color}"></span>
        <span><strong class="font-semibold">Z{z.zone}</strong> {z.name}</span>
        <span class="font-mono text-[11px] text-text2">{z.range}</span>
        <span class="text-right font-mono text-[12px] text-text1">{z.pct}%</span>
        <span class="text-right font-mono text-[12px]">{z.time}</span>
      </li>
    {/each}
  </ul>

  <div class="mt-auto flex gap-3 items-start px-3.5 py-3 rounded-[14px] bg-bg1 border border-dashed border-popover-border">
    <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">SPLIT</span>
    <span class="text-[13px] leading-[1.45] text-text1">{insight}</span>
  </div>
  <a
    href="/profile/training-settings"
    class="text-[12px] text-text2 no-underline hover:text-text0"
    onclick={(e) => { e.preventDefault(); navTo('/profile/training-settings'); }}
  >{#if lthr || ftp}Zones from {#if lthr}LTHR {lthr}{/if}{#if lthr && ftp} · {/if}{#if ftp}FTP {ftp} W{/if} — edit in Training settings{:else}Set your thresholds in Training settings{/if}</a>
</section>
