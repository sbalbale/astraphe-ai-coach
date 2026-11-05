<script lang="ts">
  import { stageMinutes } from '$lib/utils/sleepStages';
  /**
   * Wide Body view, Sleep (design: WBody): a large hypnogram with stage highlight, the
   * night's summary, naps, and the last 7 nights. Gets the Sleep page's own night data.
   */
  import EmptyStateCard from '$lib/components/ui/EmptyStateCard.svelte';
  import { boundedScoreCssColor, sleepDebtCssColor } from '$lib/scoreColors';
  import { formatMinutes, hourTicks } from '$lib/utils/bodyWide';

  type Seg = { stage: string; start_at: string; end_at: string };
  type Night = { rawDate: string; day: string; label: string; missing: boolean; durationRaw?: number; score?: number | null };

  let {
    night,
    nights,
    selected,
    onSelect,
    title,
    tip,
    hour12 = true,
    onLog,
    onCheckSync,
    checking = false,
    emptyTitle
  }: {
    /** The Sleep page's NightData for the picked night, or null when none. */
    night: Record<string, any> | null;
    nights: Night[];
    selected: number;
    onSelect: (i: number) => void;
    title: string;
    tip: string | null;
    hour12?: boolean;
    onLog: () => void;
    onCheckSync: () => void;
    checking?: boolean;
    emptyTitle: string;
  } = $props();

  type StageKey = 'awake' | 'light' | 'deep' | 'rem';
  const STAGE_COLOR: Record<StageKey, string> = {
    deep: 'var(--stage-deep)',
    light: 'var(--stage-light)',
    rem: 'var(--violet)',
    awake: 'var(--text2)'
  };
  const ROW_Y: Record<string, number> = { awake: 12, rem: 36, light: 60, deep: 84 };
  const W = 314;

  let highlight = $state<StageKey | null>(null);
  $effect(() => {
    void night?.rawDate;
    highlight = null;
  });

  const hyp = $derived.by(() => {
    const segs = ((night?.stageSegments ?? []) as Seg[])
      .map((x) => ({ stage: x.stage, a: Date.parse(x.start_at), b: Date.parse(x.end_at) }))
      .filter((x) => Number.isFinite(x.a) && Number.isFinite(x.b) && x.b > x.a && x.stage in ROW_Y)
      .sort((p, q) => p.a - q.a);
    if (segs.length < 2) return null;
    const t0 = segs[0].a;
    const t1 = segs[segs.length - 1].b;
    const px = (t: number) => Math.round(((t - t0) / (t1 - t0)) * W * 10) / 10;
    const bars = segs.map((s) => ({ x1: px(s.a), x2: Math.max(px(s.b), px(s.a) + 1), y: ROW_Y[s.stage], stage: s.stage as StageKey }));
    // Thin step line joining the stages (vertical connectors), as on the phone.
    const path = bars.map((bar, i) => `${i === 0 ? 'M' : 'L'}${bar.x1},${bar.y} L${bar.x2},${bar.y}`).join(' ');
    return { bars, path, ticks: hourTicks(t0, t1, 2, hour12) };
  });

  function opacity(stage: StageKey): number {
    if (!highlight || highlight === stage) return stage === 'light' ? 0.7 : 1;
    return 0.12;
  }

  const stages = $derived.by(() => {
    if (!night) return [];
    const pct = { deep: Number(night.deep) || 0, rem: Number(night.rem) || 0, light: Number(night.light) || 0, awake: Number(night.awake) || 0 };
    const m = stageMinutes(Number(night.inBedRaw) || 0, Number(night.durationRaw) || 0, pct);
    return [
      { key: 'awake' as const, name: 'Awake', pct: pct.awake, mins: m.awake },
      { key: 'light' as const, name: 'Light', pct: pct.light, mins: m.light },
      { key: 'deep' as const, name: 'Deep', pct: pct.deep, mins: m.deep },
      { key: 'rem' as const, name: 'REM', pct: pct.rem, mins: m.rem }
    ];
  });

  const stats = $derived.by(() => {
    if (!night) return [];
    const eff = night.inBedRaw > 0 ? Math.round((night.durationRaw / night.inBedRaw) * 100) : null;
    return [
      { k: 'Asleep', v: night.duration, c: 'var(--text0)' },
      { k: 'In bed', v: night.inBed, c: 'var(--text0)' },
      { k: 'Efficiency', v: eff === null ? '--' : `${eff}%`, c: eff !== null && eff >= 85 ? 'var(--green)' : 'var(--text0)' },
      { k: 'Sleep debt', v: night.debt == null ? '--' : formatMinutes(night.debt), c: night.debt == null ? 'var(--text2)' : sleepDebtCssColor(night.debt) }
    ];
  });

  const naps = $derived(((night?.periods ?? []) as any[]).filter((p) => p?.is_nap));
</script>

<div class="flex-1 min-h-0 grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-4">
  {#if night}
    <section aria-label="Sleep stages" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
      <div class="flex justify-between items-baseline">
        <h2 class="m-0 font-display font-normal text-[26px]">{title}</h2>
        {#if night.bedtime !== 'N/A'}
          <span class="font-mono text-[11px] text-text2">{night.bedtime} → {night.wakeup}</span>
        {/if}
      </div>
      {#if night.stagesAvailable}
        {#if hyp}
          <svg width="100%" height="190" viewBox="0 0 {W} 96" preserveAspectRatio="none" role="img" aria-label="Sleep stage timeline" class="block">
            {#each [12, 36, 60, 84] as y (y)}<line x1="0" y1={y} x2={W} y2={y} stroke="var(--bg3)" vector-effect="non-scaling-stroke"></line>{/each}
            <path d={hyp.path} fill="none" stroke="var(--border)" stroke-width="1" vector-effect="non-scaling-stroke"></path>
            {#each hyp.bars as bar, i (i)}
              <line x1={bar.x1} y1={bar.y} x2={bar.x2} y2={bar.y} stroke={STAGE_COLOR[bar.stage]} stroke-width="10" stroke-opacity={opacity(bar.stage)}></line>
            {/each}
          </svg>
          {#if hyp.ticks.length}
            <div aria-hidden="true" class="relative h-3 font-mono text-[10px] text-text3">
              {#each hyp.ticks as t (t.label + t.pct)}
                <span class="absolute -translate-x-1/2 whitespace-nowrap" style="left: {t.pct}%">{t.label}</span>
              {/each}
            </div>
          {/if}
        {:else}
          <div aria-hidden="true" class="flex gap-[3px] h-3">
            {#each stages as s (s.key)}
              <span class="rounded-[3px]" style="flex: {Math.max(s.pct, 1)} 1 0; background: {STAGE_COLOR[s.key]}; opacity: {opacity(s.key)}"></span>
            {/each}
          </div>
        {/if}
        <div role="group" aria-label="Highlight a stage" class="grid grid-cols-4 gap-2">
          {#each stages as s (s.key)}
            {@const on = highlight === s.key}
            <button
              type="button"
              aria-pressed={on}
              class="flex flex-col items-start gap-[3px] px-3 py-2.5 rounded-[14px] text-left cursor-pointer text-text0 border {on ? 'bg-accent-surface' : 'bg-bg1 border-rail-border'}"
              style={on ? `border-color: ${STAGE_COLOR[s.key]}` : ''}
              onclick={() => (highlight = on ? null : s.key)}
            >
              <span class="flex items-center gap-1.5 text-[12px] text-text2"><span aria-hidden="true" class="w-2 h-2 rounded-[2px]" style="background: {STAGE_COLOR[s.key]}"></span>{s.name}</span>
              <span class="text-[18px] font-medium">{formatMinutes(s.mins)}</span>
              <span class="font-mono text-[11px] text-text2">{Math.round(s.pct)}%</span>
            </button>
          {/each}
        </div>
      {:else}
        <p class="m-0 text-[13px] leading-[1.45] text-text2">This source gave duration and score but no REM, deep, light or awake breakdown.</p>
      {/if}
      {#if tip}
        <div class="mt-auto flex gap-3 items-start px-3.5 py-3 rounded-[14px] bg-bg1 border border-dashed border-popover-border">
          <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">TIP</span>
          <span class="text-[13px] leading-[1.45] text-text0/85">{tip}</span>
        </div>
      {/if}
    </section>
  {:else}
    <div class="flex flex-col">
      <EmptyStateCard
        icon="moon"
        tone="amber"
        eyebrow="Waiting for sync"
        title={emptyTitle}
        message="Your watch may not have synced, or it wasn't worn that night. Synced sleep replaces anything you log by hand."
        actionLabel="Log sleep"
        onAction={onLog}
        secondaryLabel={checking ? 'Checking…' : 'Check sync now'}
        onSecondary={onCheckSync}
      />
    </div>
  {/if}

  <section aria-label="Sleep summary" class="bg-bg2 border border-border rounded-[24px] px-[22px] py-5 flex flex-col gap-3.5">
    <div class="flex justify-between items-center">
      <h2 class="m-0 font-display font-normal text-[26px]">Summary</h2>
      <button type="button" class="h-[34px] px-3 rounded-[10px] border border-popover-border bg-transparent text-text0 text-[13px] font-medium cursor-pointer" onclick={onLog}>+ Log sleep</button>
    </div>
    {#if night}
      <dl class="m-0 grid grid-cols-2 gap-2">
        {#each stats as x (x.k)}
          <div class="px-3.5 py-3 rounded-[14px] bg-bg1 flex flex-col-reverse gap-0.5">
            <dt class="text-[11px] text-text2">{x.k}</dt>
            <dd class="m-0 text-[20px] font-medium" style="color: {x.c}">{x.v}</dd>
          </div>
        {/each}
      </dl>
    {/if}
    {#if naps.length}
      <div class="flex flex-col gap-2">
        <span class="font-mono text-[10px] tracking-[0.14em] text-text2">{naps.length > 1 ? 'NAPS' : 'NAP'}</span>
        {#each naps as nap (nap?.id ?? nap?.started_at)}
          <div class="flex items-center justify-between px-3.5 py-2.5 rounded-[14px] bg-bg1">
            <span class="font-mono text-[12px] text-text2">{nap.timeRange}</span>
            <span class="font-mono text-[13px] text-text0">{nap.duration}</span>
          </div>
        {/each}
      </div>
    {/if}
    <div class="mt-auto flex flex-col gap-2">
      <span class="font-mono text-[10px] tracking-[0.14em] text-text2">LAST 7 NIGHTS · HOURS ASLEEP · COLOUR = SLEEP SCORE</span>
      <div class="h-[110px] flex items-end gap-2">
        {#each nights as n, i (n.rawDate)}
          {@const mins = n.missing ? 0 : Number(n.durationRaw) || 0}
          <button
            type="button"
            class="flex-1 h-full p-0 border-0 bg-transparent cursor-pointer flex flex-col justify-end items-stretch gap-1.5"
            aria-label="{n.label}: {mins > 0 ? formatMinutes(mins) : 'no sleep recorded'}"
            aria-pressed={i === selected}
            onclick={() => onSelect(i)}
          >
            {#if mins > 0}
              <span
                aria-hidden="true"
                class="block rounded-md {i === selected ? 'ring-1 ring-text0/60' : ''}"
                style="height: {Math.max(6, Math.min(100, Math.round((mins / 540) * 100)))}%; background: {n.score ? boundedScoreCssColor(n.score) : 'var(--text3)'}; opacity: {i === selected ? 1 : 0.75}"
              ></span>
            {:else}
              <span aria-hidden="true" class="block h-full rounded-md border border-dashed {i === selected ? 'border-amber/50' : 'border-popover-border'}"></span>
            {/if}
            <span class="font-mono text-[10px] text-center {i === selected ? 'text-text0' : 'text-text2'}">{n.day}</span>
          </button>
        {/each}
      </div>
    </div>
  </section>
</div>
