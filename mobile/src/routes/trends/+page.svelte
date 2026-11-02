<script lang="ts">
  import { onMount } from 'svelte';
  import { format, startOfWeek, subDays } from 'date-fns';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import MultiLineChart from '$lib/components/charts/MultiLineChart.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { pageHeader, resetPageHeader } from '$lib/stores/pageHeader.svelte';
  import { formCssColor } from '$lib/scoreColors';

  onMount(() => {
    athleteStore.fetchAll();
  });

  $effect(() => {
    pageHeader.eyebrow = 'Last 12 weeks';
    return resetPageHeader;
  });

  type LoadRow = { date: string; day: string; ctl: number; atl: number; tsb?: number; daily_tss?: number };

  const rows = $derived.by<LoadRow[]>(() =>
    [...(athleteStore.metrics?.trainingLoadData ?? [])]
      .filter((r: any) => r?.date)
      .sort((a: any, b: any) => String(a.date).localeCompare(String(b.date)))
  );
  const windowRows = $derived(rows.filter((r) => r.date >= format(subDays(new Date(), 83), 'yyyy-MM-dd')));
  const latest = $derived(rows.length ? rows[rows.length - 1] : null);
  const ftp = $derived(Number(athleteStore.profile?.ftp_watts) || 0);

  /** Fitness change over the last 28 days. */
  const fitnessDelta = $derived.by(() => {
    if (!latest || rows.length < 29) return null;
    const then = rows[rows.length - 29];
    return Math.round((latest.ctl - then.ctl) * 10) / 10;
  });

  /** Weekly TSS for the last 12 Monday-start weeks, oldest first. */
  const weeks = $derived.by(() => {
    const start = startOfWeek(subDays(new Date(), 11 * 7), { weekStartsOn: 1 });
    const buckets = Array.from({ length: 12 }, (_, i) => ({
      start: new Date(start.getFullYear(), start.getMonth(), start.getDate() + i * 7),
      tss: 0
    }));
    for (const r of rows) {
      const d = new Date(r.date + 'T00:00:00');
      const idx = Math.floor((d.getTime() - buckets[0].start.getTime()) / (7 * 24 * 3600 * 1000));
      if (idx >= 0 && idx < 12) buckets[idx].tss += Number(r.daily_tss) || 0;
    }
    return buckets.map((b) => ({ ...b, tss: Math.round(b.tss) }));
  });
  const maxTss = $derived(Math.max(1, ...weeks.map((w) => w.tss)));
  const avgTss = $derived(Math.round(weeks.reduce((a, w) => a + w.tss, 0) / Math.max(1, weeks.filter((w) => w.tss > 0).length)));

  const fmt1 = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? '--' : n.toFixed(1));
</script>

<div class="flex flex-col gap-3.5">
  {#if athleteStore.initialLoadDone && rows.length === 0}
    <EmptyState title="No trend data yet" message="Your fitness and fatigue trends appear once a few weeks of workouts have synced." icon="📈" />
  {:else}
    <dl class="m-0 grid grid-cols-4 gap-2">
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fitness</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{fmt1(latest?.ctl)}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Fatigue</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{fmt1(latest?.atl)}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">Form</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]" style="color: {latest?.tsb == null ? 'var(--text0)' : formCssColor(latest.tsb)}">{latest?.tsb == null ? '--' : `${latest.tsb > 0 ? '+' : ''}${latest.tsb.toFixed(1)}`}</dd></div>
      <div class="bg-bg2 border border-border rounded-2xl px-2.5 py-3 flex flex-col-reverse gap-0.5"><dt class="text-[11px] text-text2">FTP</dt><dd class="m-0 text-[19px] font-medium tracking-[-0.02em]">{ftp || '--'}{#if ftp}<span class="text-[11px] text-text2 font-normal"> W</span>{/if}</dd></div>
    </dl>

    <section aria-label="Training load" class="bg-bg2 border border-border rounded-[24px] px-[18px] pt-[18px] pb-3.5 flex flex-col gap-2.5">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">Training load</h2>
        {#if fitnessDelta !== null}
          <span class="text-xs" style="color: {fitnessDelta >= 0 ? 'var(--green)' : 'var(--amber)'}">{fitnessDelta >= 0 ? '+' : ''}{fitnessDelta} in 4 wks</span>
        {/if}
      </div>
      {#if windowRows.length > 1}
        <MultiLineChart data={windowRows} height={124} />
      {/if}
      <div class="flex gap-4 text-[11px] text-text2">
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 bg-chartCtl"></span>Fitness (42d)</span>
        <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 border-t-2 border-dashed border-chartAtl"></span>Fatigue (7d)</span>
        {#if windowRows.length > 1}
          <span class="ml-auto font-mono uppercase">{format(new Date(windowRows[0].date + 'T00:00:00'), 'MMM')} → {format(new Date(windowRows[windowRows.length - 1].date + 'T00:00:00'), 'MMM')}</span>
        {/if}
      </div>
    </section>

    <section aria-label="Weekly TSS" class="bg-bg2 border border-border rounded-[24px] p-[18px] flex flex-col gap-3">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-2xl">Weekly TSS</h2>
        <span class="font-mono text-[11px] text-text2">AVG {avgTss}</span>
      </div>
      <div role="img" aria-label="Weekly TSS over the last 12 weeks" class="flex items-end gap-1.5 h-[72px]">
        {#each weeks as w, i (i)}
          <span
            class="flex-1 block rounded"
            style="height: {Math.max(2, Math.round((w.tss / maxTss) * 72))}px; background: {i === weeks.length - 1 ? 'var(--blue)' : 'var(--bg3)'}"
            title="{format(w.start, 'd MMM')}: {w.tss} TSS"
          ></span>
        {/each}
      </div>
      <div class="flex justify-between font-mono text-[10px] text-text2">
        <span>W{format(weeks[0].start, 'I')}</span><span>W{format(weeks[5].start, 'I')}</span><span>THIS WK</span>
      </div>
    </section>
  {/if}
</div>
