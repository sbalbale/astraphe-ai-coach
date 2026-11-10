<script lang="ts">
  /**
   * Full-day heart rate (design: HeartDay; phone PHeart, wide WHeart). Chart of the
   * athlete's all-day series with sleep / workouts / detected activities shaded,
   * hover-to-read and drag-to-zoom, zoom presets, the day's timeline, time in zone and
   * a week of resting HR. `wide` moves the stats and side cards into a 300 px column.
   */
  import { addDays, format, parseISO, subDays } from 'date-fns';
  import { api } from '$lib/api';
  import type { HeartRateDay } from '$lib/types/heartRate';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { bodyDate, rememberBodyDate } from '$lib/stores/bodyDate.svelte';
  import { hrZoneAnchorLabel } from '$lib/hrZoneDisplay';
  import {
    buildDayModel,
    chartPath,
    chartRange,
    clockAt,
    formatMins,
    rangeStats,
    restFloor,
    restingVsAverage,
    sameRange,
    tickMinutes,
    zoneMinutes,
    zoneOf,
    zoomPresets,
    type DaySpan,
    type SpanKind,
    type ZoneDef
  } from '$lib/utils/heartDay';

  let { wide = false, sourceLabel = $bindable('') }: { wide?: boolean; sourceLabel?: string } = $props();

  const SLEEP = '#4C7CF0';
  const COL: Record<SpanKind, string> = { sleep: SLEEP, workout: 'var(--blue)', detected: 'var(--amber)' };
  const ZONE_COL = (z: number) => `var(--zone-${z})`;
  const MAX_BACK_DAYS = 365;

  const todayStr = format(new Date(), 'yyyy-MM-dd');
  let day = $state(bodyDate.value ?? todayStr);
  let data = $state<HeartRateDay | null>(null);
  let loading = $state(true);
  let zoom = $state<[number, number] | null>(null);
  let hover = $state<number | null>(null);
  let dragA = $state<number | null>(null);
  let dragB = $state<number | null>(null);

  let reqId = 0;
  $effect(() => {
    const d = day;
    rememberBodyDate(d, todayStr);
    const id = ++reqId;
    loading = true;
    void api.getHeartRateDay(d).then((res) => {
      if (id !== reqId) return;
      data = res;
      loading = false;
    });
  });

  function setDay(d: string) {
    day = d;
    zoom = null;
    hover = null;
  }
  const atToday = $derived(day >= todayStr);
  const atFirst = $derived(day <= format(subDays(new Date(), MAX_BACK_DAYS), 'yyyy-MM-dd'));
  const dayLabel = $derived(format(parseISO(day), 'EEE d MMM') + (atToday ? ' · so far' : ''));

  const model = $derived(data ? buildDayModel(data) : null);
  const hasData = $derived(!!model && (data?.samples.length ?? 0) > 0);
  const len = $derived(model?.len ?? 1440);
  const nowMin = $derived(
    model && atToday ? Math.min(len, Math.max(0, (Date.now() - model.dayStartMs) / 60_000)) : len
  );

  $effect(() => {
    const iv = data?.interval_sec;
    const src = data?.source;
    sourceLabel = src && iv ? `${src.toUpperCase()} ${Math.round(iv / 60)}-MINUTE HEART RATE` : 'ALL-DAY HEART RATE';
  });

  const a = $derived(zoom ? zoom[0] : 0);
  const b = $derived(zoom ? zoom[1] : len);
  const span = $derived(Math.max(1, b - a));
  const X = (m: number) => ((m - a) / span) * 1000;
  const range = $derived(chartRange(model?.hr ?? []));
  const Y = (v: number) => 200 - ((Math.max(range.lo, Math.min(range.hi, v)) - range.lo) / (range.hi - range.lo)) * 200;
  const clock = (m: number) => (model ? clockAt(model.dayStartMs, m) : '');

  const path = $derived(model ? chartPath(model.hr, a, b, Y) : '');
  const stats = $derived(model ? rangeStats(model.hr, a, b) : { avg: null, max: null, min: null, n: 0 });

  const visible = $derived(
    (model?.spans ?? [])
      .map((s) => ({ ...s, c: [Math.max(a, s.a), Math.min(b, s.b)] as [number, number] }))
      .filter((s) => s.c[1] > s.c[0])
  );
  const bands = $derived(
    visible.map((s) => ({
      x: X(s.c[0]),
      w: X(s.c[1]) - X(s.c[0]),
      c: COL[s.kind],
      op: s.kind === 'workout' ? 0.16 : 0.12
    }))
  );
  const bandLabels = $derived.by(() => {
    const out: { text: string; left: number; maxW: number; c: string }[] = [];
    let end = -Infinity;
    for (const s of visible) {
      if (s.kind === 'sleep' && (s.c[1] - s.c[0]) / span <= (wide ? 0.06 : 0.12)) continue;
      const left = X(s.c[0]) / 10;
      // A label may run past its band (min 14% wide); skip one that would collide.
      if (left < end) continue;
      const maxW = Math.max((X(s.c[1]) - X(s.c[0])) / 10, 14);
      const roomy = wide || (s.c[1] - s.c[0]) / span > 0.25;
      const text = s.kind === 'sleep' || roomy ? s.title : s.kind === 'detected' ? 'Detected' : 'Workout';
      out.push({ text, left, maxW, c: COL[s.kind] });
      end = left + maxW;
    }
    return out;
  });

  const zones = $derived(
    ((athleteStore.profile?.hr_zones?.zones ?? []) as ZoneDef[]).filter((z) => z.zone >= 1 && z.zone <= 5)
  );
  const zlines = $derived(
    zones.slice(1).map((z) => ({ id: `Z${z.zone}`, c: ZONE_COL(z.zone), y: Y(z.min) })).filter((z) => z.y > 0 && z.y < 200)
  );
  const floor = $derived(restFloor(athleteStore.profile?.max_hr));
  const zoneMins = $derived(model ? zoneMinutes(model.hr, a, b, zones, floor) : {});
  const zoneMax = $derived(Math.max(1, ...Object.values(zoneMins)));
  const anchor = $derived(hrZoneAnchorLabel(athleteStore.profile));

  const ticks = $derived(
    tickMinutes(a, b, !wide).map((m) => ({
      m,
      label: m >= len ? '24:00' : clock(m),
      shift: m === a ? '0' : m === b ? '-100%' : '-50%'
    }))
  );

  const presets = $derived(model ? zoomPresets(model) : []);

  function pad(s: DaySpan): [number, number] {
    return [Math.max(0, s.a - 15), Math.min(len, s.b + 15)];
  }

  const events = $derived(
    (model?.spans ?? []).map((s) => {
      const es = rangeStats(model!.hr, s.a, Math.min(s.b, nowMin));
      const sub = s.kind === 'sleep' ? `low ${es.min ?? '—'}` : `max ${es.max ?? '—'}`;
      const when =
        `${clock(s.a)} – ${s.b >= len ? 'into tomorrow' : clock(s.b)} · ${formatMins(s.b - s.a)}` +
        (s.kind === 'detected' ? ' · found in your heart rate' : '');
      return { s, es, sub, when, on: sameRange(pad(s), zoom) };
    })
  );

  const readout = $derived.by(() => {
    if (hover !== null && model) {
      const v = model.hr[hover];
      if (v !== null && v !== undefined) {
        const inS = model.spans.find((s) => hover! >= s.a && hover! < s.b);
        const z = v >= floor ? zoneOf(v, zones) : null;
        return `${clock(hover)} · ${v} bpm${z ? ` · Z${z}` : ''}${inS ? ` · ${inS.title}` : ''}`;
      }
    }
    if (zoom) return `${clock(a)}–${clock(b)} · avg ${stats.avg ?? '—'} bpm`;
    return `${atToday ? 'Today so far' : format(parseISO(day), 'EEE d MMM')} · ${stats.avg ?? '—'} bpm average`;
  });
  const hoverVal = $derived(hover !== null && model ? model.hr[hover] ?? null : null);

  const rhrDelta = $derived(data ? restingVsAverage(data.resting_hr_history, day) : null);
  const rhrWeek = $derived.by(() => {
    const hist = new Map((data?.resting_hr_history ?? []).map((h) => [h.date, h.resting_hr]));
    return Array.from({ length: 7 }, (_, i) => {
      const d = format(subDays(parseISO(day), 6 - i), 'yyyy-MM-dd');
      const v = hist.get(d) ?? null;
      return { d, letter: format(parseISO(d), 'EEEEE'), v, on: d === day };
    });
  });
  const rhrLo = $derived(Math.min(...rhrWeek.map((r) => r.v ?? 999)) - 6);

  const statTiles = $derived([
    { k: 'Resting', v: data?.resting_hr ?? null, c: 'var(--green)' },
    { k: zoom ? 'Avg (range)' : 'Average', v: stats.avg, c: 'var(--text0)' },
    { k: 'Max', v: stats.max, c: 'var(--red)' },
    { k: 'Min', v: stats.min, c: '#8DB3E8' }
  ]);

  // ---- pointer: hover to read, drag to zoom ----
  function mAt(e: PointerEvent): number {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    return Math.min(len - 1, Math.round(a + f * span));
  }
  function pDown(e: PointerEvent) {
    const m = mAt(e);
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* not capturable (synthetic event) */
    }
    dragA = m;
    dragB = m;
    hover = m;
  }
  function pMove(e: PointerEvent) {
    const m = mAt(e);
    if (dragA !== null) dragB = m;
    hover = m;
  }
  function pUp(e: PointerEvent) {
    const m = mAt(e);
    const s0 = dragA;
    dragA = null;
    dragB = null;
    if (s0 !== null && Math.abs(m - s0) >= 10) {
      zoom = [Math.min(s0, m), Math.max(s0, m)];
      hover = null;
    } else hover = m;
  }
  function pLeave() {
    if (dragA === null) hover = null;
  }
  const dragging = $derived(dragA !== null && dragB !== null && Math.abs(dragB - dragA) > 2);
  const chartH = $derived(wide ? 300 : 190);
</script>

{#snippet statGrid(big: boolean)}
  <dl class="m-0 grid {big ? 'grid-cols-2 gap-2' : 'grid-cols-4 gap-1.5'}">
    {#each statTiles as x (x.k)}
      <div class="bg-bg2 border border-border flex flex-col-reverse gap-0.5 {big ? 'p-3.5 rounded-2xl' : 'p-2.5 rounded-[14px]'}">
        <dt class="text-text2 {big ? 'text-[11px]' : 'text-[10px]'}">{x.k}</dt>
        <dd class="m-0 font-medium {big ? 'text-[26px] tracking-[-0.02em]' : 'text-[18px]'}" style="color: {x.c}">
          {x.v ?? '—'}<span class="text-text2 {big ? 'text-[12px]' : 'text-[10px]'}"> bpm</span>
        </dd>
      </div>
    {/each}
  </dl>
{/snippet}

{#snippet sideCards()}
  <section aria-label="Time in zone" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-2.5">
    <div class="flex justify-between items-baseline">
      <h3 class="m-0 font-display font-normal text-[22px]">Time in zone</h3>
      <span class="font-mono text-[10px] text-text2">{zoom ? `${clock(a)}–${clock(b)}` : 'WHOLE DAY'}</span>
    </div>
    {#if zones.length}
      {#each zones as z (z.zone)}
        {@const mins = zoneMins[z.zone] ?? 0}
        <div class="grid grid-cols-[26px_1fr_52px] gap-2.5 items-center text-[12px]">
          <span class="font-mono" style="color: {ZONE_COL(z.zone)}">Z{z.zone}</span>
          <span aria-hidden="true" class="h-2 rounded bg-border overflow-hidden">
            <span class="block h-2 rounded" style="background: {ZONE_COL(z.zone)}; width: {((mins / zoneMax) * 100).toFixed(1)}%"></span>
          </span>
          <span class="text-right font-mono text-text1">{formatMins(mins)}</span>
        </div>
      {/each}
      <span class="text-[11px] text-text3">Zones from {anchor ?? 'your profile'} · under {floor} bpm counts as rest</span>
    {:else}
      <span class="text-[12px] text-text2">Set a max or threshold heart rate in Training settings to see zones.</span>
    {/if}
  </section>

  <section aria-label="Resting heart rate" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-2.5">
    <div class="flex justify-between items-baseline">
      <h3 class="m-0 font-display font-normal text-[22px]">Resting HR</h3>
      {#if rhrDelta !== null}
        <span class="text-[12px]" style="color: {rhrDelta <= 0 ? 'var(--green)' : 'var(--amber)'}">
          {rhrDelta === 0 ? 'At' : rhrDelta < 0 ? `↓ ${-rhrDelta}` : `↑ ${rhrDelta}`} vs 30-day avg
        </span>
      {/if}
    </div>
    <div class="flex items-end gap-2 h-[70px]">
      {#each rhrWeek as r (r.d)}
        <span class="flex-1 h-full flex flex-col justify-end gap-1">
          <span class="font-mono text-[10px] text-center" style="color: {r.on ? 'var(--text0)' : 'var(--text2)'}">{r.v ?? '–'}</span>
          <span
            class="block rounded-[5px]"
            style="height: {r.v ? Math.max(4, Math.min(44, (r.v - rhrLo) * 3.2)) : 2}px; background: {r.on ? 'var(--green)' : '#34343A'}"
          ></span>
          <span class="font-mono text-[10px] text-text2 text-center">{r.letter}</span>
        </span>
      {/each}
    </div>
    <span class="text-[12px] leading-[1.45] text-text1">Your lowest sustained heart rate of the day. Lower than usual means you're absorbing training well.</span>
  </section>
{/snippet}

<div class={wide ? 'grid grid-cols-[minmax(0,1fr)_300px] gap-5 items-start' : 'flex flex-col gap-3'}>
  <div class="flex flex-col gap-3 min-w-0">
    <!-- Day switcher -->
    <div class="flex items-center gap-2">
      <div class="flex-1 flex items-center h-11 rounded-xl bg-bg2 border border-border">
        <button
          type="button"
          aria-label="Previous day"
          disabled={atFirst}
          onclick={() => setDay(format(subDays(parseISO(day), 1), 'yyyy-MM-dd'))}
          class="w-11 h-11 flex items-center justify-center bg-transparent border-0 {atFirst ? 'text-[#3E3E44]' : 'text-text1 cursor-pointer'}"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"></path></svg>
        </button>
        <span class="flex-1 text-center text-[14px] font-medium">{dayLabel}</span>
        <button
          type="button"
          aria-label="Next day"
          disabled={atToday}
          onclick={() => setDay(format(addDays(parseISO(day), 1), 'yyyy-MM-dd'))}
          class="w-11 h-11 flex items-center justify-center bg-transparent border-0 {atToday ? 'text-[#3E3E44]' : 'text-text1 cursor-pointer'}"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
        </button>
      </div>
      <button
        type="button"
        disabled={atToday}
        onclick={() => setDay(todayStr)}
        class="h-11 px-3 rounded-xl text-[13px] font-semibold {atToday ? 'bg-transparent border border-border text-[#5A5A62]' : 'bg-blue border-0 text-on-accent cursor-pointer'}"
      >Today</button>
    </div>

    {#if !wide}{@render statGrid(false)}{/if}

    {#if loading && !data}
      <div class="bg-bg2 border border-border rounded-[24px] h-[260px] animate-pulse" aria-label="Loading heart rate"></div>
    {:else if !hasData}
      <div class="bg-bg2 border border-border rounded-[24px] p-6 flex flex-col gap-1.5">
        <span class="text-[14px] font-medium">No heart rate for this day</span>
        <span class="text-[13px] leading-[1.45] text-text1">
          All-day heart rate comes from a connected Garmin. It syncs about once an hour, so today fills in as the day goes.
        </span>
      </div>
    {:else}
      <!-- Chart -->
      <section aria-label="Heart rate over the day" class="bg-bg2 border border-border rounded-[24px] pt-3.5 px-3.5 pb-3 flex flex-col gap-2">
        <div class="flex justify-between items-center min-h-8 gap-2">
          <span aria-live="polite" class="font-mono text-[11px] tracking-[0.04em] {hover !== null ? 'text-text0' : 'text-text2'}">{readout}</span>
          {#if zoom}
            <button
              type="button"
              onclick={() => { zoom = null; hover = null; }}
              class="flex-none h-8 px-2.5 rounded-[9px] border border-popover-border bg-transparent text-text0 text-[12px] font-medium cursor-pointer"
            >Whole day</button>
          {/if}
        </div>
        <div aria-hidden="true" class="relative h-4">
          {#each bandLabels as l, i (i)}
            <span
              class="absolute top-0 whitespace-nowrap overflow-hidden text-ellipsis font-mono text-[9px] tracking-[0.06em] uppercase"
              style="color: {l.c}; left: {l.left.toFixed(2)}%; max-width: {l.maxW.toFixed(2)}%"
            >{l.text}</span>
          {/each}
        </div>
        <div class="relative" style="height: {chartH}px">
          <svg width="100%" height={chartH} viewBox="0 0 1000 200" preserveAspectRatio="none" role="img" aria-label="Heart rate across {dayLabel}, with sleep and workouts shaded" class="block">
            {#each bands as bd, i (i)}
              <rect x={bd.x.toFixed(1)} y="0" width={bd.w.toFixed(1)} height="200" fill={bd.c} fill-opacity={bd.op}></rect>
            {/each}
            {#each zlines as z (z.id)}
              <line x1="0" y1={z.y.toFixed(1)} x2="1000" y2={z.y.toFixed(1)} stroke={z.c} stroke-opacity="0.35" stroke-dasharray="4 5" vector-effect="non-scaling-stroke"></line>
            {/each}
            <path d={path} fill="none" stroke="var(--red)" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>
            {#if atToday && nowMin > a && nowMin < b}
              <line x1={X(nowMin).toFixed(1)} y1="0" x2={X(nowMin).toFixed(1)} y2="200" stroke="var(--text0)" stroke-opacity="0.35" stroke-dasharray="2 4" vector-effect="non-scaling-stroke"></line>
            {/if}
            {#if dragging && dragA !== null && dragB !== null}
              <rect x={X(Math.min(dragA, dragB)).toFixed(1)} y="0" width={Math.abs(X(dragB) - X(dragA)).toFixed(1)} height="200" fill="var(--blue)" fill-opacity="0.15"></rect>
            {/if}
          </svg>
          <div aria-hidden="true" class="absolute right-0.5 top-0 bottom-0 pointer-events-none">
            {#each zlines as z (z.id)}
              <span class="absolute right-0 -translate-y-[110%] font-mono text-[9px] opacity-80" style="color: {z.c}; top: {(z.y / 2).toFixed(1)}%">{z.id}</span>
            {/each}
          </div>
          {#if hover !== null && hoverVal !== null}
            <span aria-hidden="true" class="absolute top-0 bottom-0 w-px bg-[rgba(237,235,230,0.45)] pointer-events-none" style="left: {(X(hover) / 10).toFixed(2)}%"></span>
            <span
              aria-hidden="true"
              class="absolute w-2.5 h-2.5 -ml-[5px] -mt-[5px] rounded-full bg-red pointer-events-none shadow-[0_0_0_3px_var(--bg2)]"
              style="left: {(X(hover) / 10).toFixed(2)}%; top: {(Y(hoverVal) / 2).toFixed(2)}%"
            ></span>
          {/if}
          <div
            role="presentation"
            onpointerdown={pDown}
            onpointermove={pMove}
            onpointerup={pUp}
            onpointerleave={pLeave}
            class="absolute inset-0 cursor-crosshair touch-none"
          ></div>
        </div>
        <div aria-hidden="true" class="relative h-3.5 font-mono text-[10px] text-text3">
          {#each ticks as t (t.m)}
            <span class="absolute top-0" style="left: {(X(t.m) / 10).toFixed(2)}%; transform: translateX({t.shift})">{t.label}</span>
          {/each}
        </div>
        <div class="flex gap-3 flex-wrap text-[11px] text-text2">
          <span class="flex items-center gap-[5px]"><span class="w-2.5 h-2.5 rounded-sm" style="background: rgba(76,124,240,0.35)"></span>Sleep</span>
          <span class="flex items-center gap-[5px]"><span class="w-2.5 h-2.5 rounded-sm" style="background: rgba(127,180,255,0.35)"></span>Workout</span>
          <span class="flex items-center gap-[5px]"><span class="w-2.5 h-2.5 rounded-sm" style="background: rgba(255,203,136,0.3)"></span>Detected</span>
          <span class="ml-auto text-text3">{wide ? 'Hover to read · drag to zoom' : 'Touch to read · drag to zoom'}</span>
        </div>
      </section>

      <!-- Zoom chips -->
      <div role="group" aria-label="Zoom to" class="flex gap-1.5 flex-wrap">
        {#each presets as z, i (i)}
          {@const on = sameRange(z.r, zoom)}
          <button
            type="button"
            aria-pressed={on}
            onclick={() => { zoom = z.r; hover = null; }}
            class="min-h-9 px-3 rounded-[10px] text-[12px] font-medium cursor-pointer border {on ? 'bg-accent-surface border-blue text-text0' : 'bg-transparent border-popover-border text-text1 hover:border-[#3A3A42]'}"
          >{z.label}</button>
        {/each}
      </div>

      <!-- Day timeline -->
      {#if events.length}
        <section aria-label="Day timeline" class="flex flex-col gap-1.5">
          <span class="px-1 pt-1 font-mono text-[11px] tracking-[0.14em] text-text2">THE DAY</span>
          {#each events as e, i (i)}
            <div class="flex items-center gap-2.5 min-h-14 py-2 px-3 rounded-2xl border hover:bg-popover {e.on ? 'bg-accent-surface border-accent-surface-border' : 'bg-bg1 border-rail-border'}">
              <button
                type="button"
                onclick={() => { zoom = pad(e.s); hover = null; }}
                aria-label="Zoom to {e.s.title}"
                class="flex-1 min-w-0 flex items-center gap-3 p-0 border-0 bg-transparent text-text0 text-left cursor-pointer"
              >
                <span aria-hidden="true" class="flex-none w-2.5 h-2.5 rounded-[3px]" style="background: {COL[e.s.kind]}"></span>
                <span class="flex-1 min-w-0 flex flex-col gap-0.5">
                  <span class="text-[14px] font-medium truncate">{e.s.title}</span>
                  <span class="text-[12px] text-text2">{e.when}</span>
                </span>
                <span class="flex flex-col items-end gap-0.5">
                  <span class="font-mono text-[13px]">{e.es.avg ? `${e.es.avg} avg` : '—'}</span>
                  <span class="text-[10px] text-text2">{e.sub}</span>
                </span>
              </button>
              {#if e.s.workoutId}
                <a
                  href="/training?workout_id={encodeURIComponent(e.s.workoutId)}"
                  aria-label="Open workout"
                  class="flex-none w-9 h-9 rounded-[10px] border border-popover-border flex items-center justify-center"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text1)" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>
                </a>
              {/if}
            </div>
          {/each}
        </section>
      {/if}

      {#if !wide}{@render sideCards()}{/if}
    {/if}
  </div>

  {#if wide}
    <div class="flex flex-col gap-3 min-w-0">
      {@render statGrid(true)}
      {#if hasData}{@render sideCards()}{/if}
    </div>
  {/if}
</div>
