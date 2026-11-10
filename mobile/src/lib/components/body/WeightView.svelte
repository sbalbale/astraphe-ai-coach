<script lang="ts">
  /**
   * Weight over time (design: WeightView; phone PWeight, wide WWeight). Weigh-ins as
   * dots with a smoothed trend, goal line and projection; log, delete with undo, goal.
   * `wide` moves the cards, goal and weigh-in list into a 340 px column.
   */
  import { addDays, format, parseISO } from 'date-fns';
  import { api } from '$lib/api';
  import type { WeightPayload } from '$lib/types/weight';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { normalizeUnits } from '$lib/utils/units';
  import {
    RANGES,
    coachLine,
    daysToGoal,
    fromUnit,
    gridValues,
    r1,
    ratePerWeek,
    smooth,
    sourceLabel,
    tickOffsets,
    toUnit,
    withOffsets,
    type Entry,
    type Metric,
    type WeightUnit
  } from '$lib/utils/weightView';

  let { wide = false }: { wide?: boolean } = $props();

  let data = $state<WeightPayload | null>(null);
  let loading = $state(true);
  let unit = $state<WeightUnit | null>(null);
  let range = $state(90);
  let metric = $state<Metric>('weight');
  let hover = $state<Entry | null>(null);
  let logOpen = $state(false);
  let draft = $state<string | null>(null);
  let logDay = $state<0 | -1>(0);
  let goalOpen = $state(false);
  let goalDraft = $state('');
  let showAll = $state(false);
  let toast = $state<{ text: string; undo: () => Promise<void> } | null>(null);
  let busy = $state(false);

  async function load() {
    const res = await api.getWeight();
    if (res) data = res;
    loading = false;
  }
  $effect(() => {
    void load();
  });

  const u = $derived<WeightUnit>(
    unit ?? (normalizeUnits(data?.measurement_units ?? athleteStore.profile?.measurement_units) === 'imperial' ? 'lb' : 'kg')
  );
  const K = (kg: number) => toUnit(kg, u);

  const today = $derived(data?.today ?? format(new Date(), 'yyyy-MM-dd'));
  const entries = $derived(withOffsets(data?.entries ?? [], today));
  const hasEntries = $derived(entries.length > 0);
  const tr = $derived(smooth(entries.map((e) => ({ o: e.o, v: e.weight_kg })), -365));
  const fatPts = $derived(entries.filter((e) => e.body_fat_pct != null).map((e) => ({ o: e.o, v: e.body_fat_pct as number })));
  const fatTr = $derived(smooth(fatPts, -365));
  const isFat = $derived(metric === 'fat');

  const from = $derived(-range);
  const now = $derived(tr.get(0) ?? null);
  const firstInRange = (m: Map<number, number | null>) => {
    for (let o = from; o <= 0; o++) {
      const v = m.get(o);
      if (v != null) return v;
    }
    return null;
  };
  const then = $derived(firstInRange(tr));
  const perWk = $derived(ratePerWeek(entries, tr));
  const goal = $derived(data?.goal_weight_kg ?? null);
  const projDays = $derived(!isFat && now != null ? daysToGoal(now, goal, perWk) : 0);
  const xEnd = $derived(projDays && range <= 90 ? Math.min(projDays, Math.round(range * 0.35)) : 0);
  const inR = $derived(entries.filter((e) => e.o >= from && (!isFat || e.body_fat_pct != null)));

  const scale = $derived.by(() => {
    // The trend counts too: carried in from before the range, it can sit outside the dots.
    const T = isFat ? fatTr : tr;
    const trendVals: number[] = [];
    for (let o = from; o <= 0; o++) {
      const v = T.get(o);
      if (v != null) trendVals.push(isFat ? v : K(v));
    }
    const vals = (isFat ? inR.map((e) => e.body_fat_pct as number) : inR.map((e) => K(e.weight_kg)))
      .concat(trendVals)
      .concat(goal != null && !isFat ? [K(goal)] : []);
    if (!vals.length) return { lo: 0, hi: 1 };
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 + (isFat ? 0.3 : 0.6);
    return { lo: lo - pad, hi: hi + pad };
  });
  const X = (o: number) => ((o - from) / (range + xEnd)) * 1000;
  const Y = (v: number) => 190 - ((v - scale.lo) / (scale.hi - scale.lo)) * 180;

  const dots = $derived(
    inR.map((e) => ({
      e,
      x: X(e.o),
      y: Y(isFat ? (e.body_fat_pct as number) : K(e.weight_kg)),
      c: e.source === 'manual' ? 'var(--amber)' : 'var(--text1)'
    }))
  );
  const line = $derived.by(() => {
    const T = isFat ? fatTr : tr;
    const pts: string[] = [];
    for (let o = from; o <= 0; o++) {
      const v = T.get(o);
      if (v != null) pts.push(`${X(o).toFixed(1)},${Y(isFat ? v : K(v)).toFixed(1)}`);
    }
    return pts.join(' ');
  });
  const proj = $derived(
    xEnd && now != null && perWk != null
      ? `${X(0).toFixed(1)},${Y(K(now)).toFixed(1)} ${X(xEnd).toFixed(1)},${Y(K(now + (perWk / 7) * xEnd)).toFixed(1)}`
      : ''
  );
  const grid = $derived(
    gridValues(scale.lo, scale.hi, isFat ? 0.5 : u === 'kg' ? 1 : 2).map((v) => ({
      v,
      y: Y(v),
      label: isFat ? `${v.toFixed(1)}%` : String(Math.round(v))
    }))
  );
  const dayDate = (o: number) => addDays(parseISO(today), o);
  const ticks = $derived(
    tickOffsets(range).map((o) => ({
      o,
      label: o === 0 ? 'TODAY' : format(dayDate(o), 'd MMM').toUpperCase(),
      shift: o === 0 && !xEnd ? '-100%' : o === -range ? '0' : '-50%'
    }))
  );
  const showGoal = $derived(goal != null && !isFat);

  const readout = $derived.by(() => {
    const e = hover;
    if (!e) return isFat ? 'Body fat · smoothed' : 'Tap or drag across the chart to read a day';
    const when = format(dayDate(e.o), 'EEE d MMM');
    const val = isFat
      ? `${r1(e.body_fat_pct as number)}%`
      : `${r1(K(e.weight_kg))} ${u} · trend ${r1(K(tr.get(e.o) ?? e.weight_kg))}`;
    return `${when} · ${val} · ${sourceLabel(e.source)}`;
  });

  function pMove(ev: PointerEvent) {
    const rc = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (ev.clientX - rc.left) / rc.width));
    const o = Math.round(from + f * (range + xEnd));
    let best: Entry | null = null;
    for (const x of inR) if (!best || Math.abs(x.o - o) < Math.abs(best.o - o)) best = x;
    if (best && hover?.id !== best.id) hover = best;
  }

  // ---- cards ----
  const ftp = $derived(Number(data?.ftp_watts ?? athleteStore.profile?.ftp_watts) || null);
  const wkg = $derived(ftp && now ? ftp / now : null);
  const latest = $derived(entries.length ? entries[entries.length - 1] : null);
  const fatNow = $derived(fatTr.get(0) ?? null);
  const pctWk = $derived(perWk != null && now ? (perWk / now) * 100 : null);
  const tr90 = $derived(tr.get(-90) ?? null);
  const cards = $derived([
    {
      k: 'Rate',
      v: perWk == null ? '—' : `${perWk <= 0 ? '−' : '+'}${r1(K(Math.abs(perWk)))} ${u}/wk`,
      sub: pctWk == null ? 'Needs 2 weigh-ins in 4 weeks' : `${Math.abs(pctWk).toFixed(1)}% of body weight · 4 wk`,
      c: pctWk == null ? 'var(--text0)' : Math.abs(pctWk) <= 0.75 ? 'var(--green)' : 'var(--amber)'
    },
    {
      k: 'Power to weight',
      v: wkg ? `${wkg.toFixed(2)} W/kg` : '—',
      sub: ftp ? `FTP ${ftp} W${tr90 ? ` · was ${(ftp / tr90).toFixed(2)} in ${format(dayDate(-90), 'MMM')}` : ''}` : 'Set FTP in Training settings',
      c: 'var(--text0)'
    },
    {
      k: 'Body fat',
      v: fatNow != null ? `${r1(fatNow)}%` : '—',
      sub: fatNow != null && now ? `Lean mass ${r1(K(now * (1 - fatNow / 100)))} ${u}` : 'Log it, or sync a smart scale',
      c: 'var(--text0)'
    },
    {
      k: 'Last weigh-in',
      v: latest ? `${r1(K(latest.weight_kg))} ${u}` : '—',
      sub: latest ? whenLabel(latest) : 'None yet',
      c: 'var(--text0)'
    }
  ]);

  function whenLabel(e: Entry): string {
    const d = e.o === 0 ? 'Today' : format(dayDate(e.o), 'EEE d MMM');
    return e.time_known ? `${d} ${format(new Date(e.measured_at), 'HH:mm')}` : d;
  }

  const eta = $derived(projDays ? format(dayDate(projDays), 'EEE d MMM') : null);
  const goalText = $derived.by(() => {
    if (goal == null) return 'No goal set. Weight is tracked either way; a goal adds a target line and an ETA.';
    if (now == null) return `Goal ${r1(K(goal))} ${u}.`;
    if (Math.abs(now - goal) < 0.25) return `You're at your goal of ${r1(K(goal))} ${u}. The coach will now watch for steady weight.`;
    return (
      `Goal ${r1(K(goal))} ${u} · ${r1(K(Math.abs(now - goal)))} ${u} to go.` +
      (eta ? ` At your 4-week rate you'd get there around ${eta}.` : ' Your trend isn’t heading there yet, so there’s no ETA.')
    );
  });
  const coach = $derived(coachLine(perWk, now, u, perWk != null && perWk < 0 ? wkg : null));

  // ---- weigh-in list ----
  const desc = $derived(entries.slice().reverse());
  const rows = $derived(
    desc.slice(0, showAll ? 30 : wide ? 8 : 5).map((e) => {
      const prev = desc[desc.indexOf(e) + 1];
      const dd = prev ? K(e.weight_kg) - K(prev.weight_kg) : 0;
      return {
        e,
        val: `${r1(K(e.weight_kg))} ${u}`,
        meta: [whenLabel(e), sourceLabel(e.source), e.body_fat_pct != null ? `${r1(e.body_fat_pct)}% fat` : null]
          .filter(Boolean)
          .join(' · '),
        delta: prev ? `${dd > 0.05 ? '+' : dd < -0.05 ? '−' : '±'}${r1(Math.abs(dd))}` : '',
        dc: dd > 0.05 ? 'var(--amber)' : dd < -0.05 ? 'var(--green)' : 'var(--text2)'
      };
    })
  );

  // ---- actions ----
  const draftVal = $derived(draft ?? (latest ? r1(K(latest.weight_kg)) : u === 'kg' ? '75.0' : '165.0'));
  function step(d: number) {
    const v = parseFloat(draftVal);
    if (Number.isFinite(v)) draft = r1(v + d);
  }
  function openLog() {
    logOpen = !logOpen;
    draft = null;
    fatDraft = null;
    logDay = 0;
  }

  /** Optional body fat for the weigh-in (%), from a smart scale or a body-comp test. */
  let fatDraft = $state<number | string | null>(null);
  const fatVal = $derived(fatDraft === null || fatDraft === '' ? null : Number(fatDraft));
  const fatInvalid = $derived(fatVal !== null && !(fatVal >= 2 && fatVal <= 75));

  async function saveLog(ev: SubmitEvent) {
    ev.preventDefault();
    const v = parseFloat(draftVal);
    if (!(v > 0) || busy || fatInvalid) return;
    busy = true;
    const day = format(dayDate(logDay), 'yyyy-MM-dd');
    const body: Record<string, unknown> = { weight_kg: Math.round(fromUnit(v, u) * 100) / 100, date: day };
    if (fatVal !== null) body.body_fat_pct = Math.round(fatVal * 10) / 10;
    const res = await api.weightRequest('POST', '', body);
    busy = false;
    if (!res) return;
    const id = (res as { weigh_in?: { id?: string } }).weigh_in?.id;
    logOpen = false;
    toast = {
      text: `Logged ${r1(v)} ${u}${fatVal !== null ? ` at ${r1(fatVal)}% fat` : ''} for ${logDay === 0 ? 'today' : 'yesterday'}.`,
      undo: async () => {
        if (id) await api.weightRequest('DELETE', `/${id}`);
      }
    };
    await load();
  }

  async function remove(e: Entry) {
    if (busy) return;
    busy = true;
    const ok = await api.weightRequest('DELETE', `/${e.id}`);
    busy = false;
    if (!ok) return;
    hover = null;
    toast = {
      text: `Deleted ${r1(K(e.weight_kg))} ${u} from ${format(dayDate(e.o), 'EEE d MMM')}.`,
      undo: async () => {
        await api.weightRequest('POST', `/${e.id}/restore`);
      }
    };
    await load();
  }

  async function undo() {
    const t = toast;
    if (!t) return;
    toast = null;
    await t.undo();
    await load();
  }

  function toggleGoal() {
    goalOpen = !goalOpen;
    goalDraft = goal != null ? r1(K(goal)) : now != null ? r1(K(now) - (u === 'kg' ? 1.5 : 3)) : '';
  }
  async function saveGoal(ev: SubmitEvent) {
    ev.preventDefault();
    const v = parseFloat(goalDraft);
    if (!(v > 0)) return;
    if (await api.weightRequest('PUT', '/goal', { goal_weight_kg: Math.round(fromUnit(v, u) * 100) / 100 })) {
      goalOpen = false;
      await load();
    }
  }
  async function clearGoal() {
    if (await api.weightRequest('PUT', '/goal', { goal_weight_kg: null })) {
      goalOpen = false;
      await load();
    }
  }

  const seg = (on: boolean) =>
    `h-[30px] px-2.5 border-0 rounded-lg text-[12px] font-medium cursor-pointer ${on ? 'bg-border text-text0' : 'bg-transparent text-text2'}`;
  const chartH = $derived(wide ? 320 : 200);
  const headVal = $derived(isFat ? (fatNow != null ? r1(fatNow) : '—') : now != null ? r1(K(now)) : '—');
  const chg = $derived.by(() => {
    // A change needs readings on at least two days (one reading is compared with itself).
    const days = new Set((isFat ? fatPts : entries).map((e) => e.o));
    if (days.size < 2) return null;
    if (isFat) {
      const a = firstInRange(fatTr);
      return fatNow != null && a != null ? fatNow - a : null;
    }
    return now != null && then != null ? now - then : null;
  });
  const chgText = $derived.by(() => {
    if (chg == null) return 'No change to show yet';
    const amt = Math.abs(isFat ? chg : K(chg));
    const sign = amt < 0.05 ? '±' : chg < 0 ? '−' : '+';
    return `${sign}${r1(amt)}${isFat ? ' pts' : ` ${u}`} over ${range === 365 ? 'the last year' : `the last ${range} days`}`;
  });
</script>

{#snippet sideCol()}
  <dl class="m-0 grid grid-cols-2 gap-2">
    {#each cards as c (c.k)}
      <div class="px-3.5 py-3 rounded-2xl bg-bg2 border border-border flex flex-col-reverse gap-[3px]">
        <dt class="text-[11px] text-text2">{c.k}</dt>
        <dd class="m-0 flex flex-col gap-0.5">
          <span class="text-[19px] font-medium" style="color: {c.c}">{c.v}</span>
          <span class="text-[11px] text-text2">{c.sub}</span>
        </dd>
      </div>
    {/each}
  </dl>

  <section aria-label="Goal" class="bg-bg2 border border-border rounded-[20px] px-4 py-3.5 flex flex-col gap-2.5">
    <div class="flex justify-between items-center">
      <span class="text-[15px] font-medium">Goal</span>
      <button
        type="button"
        onclick={toggleGoal}
        aria-expanded={goalOpen}
        class="h-[34px] px-3 rounded-[10px] border border-popover-border bg-transparent text-text0 text-[12px] font-medium cursor-pointer"
      >{goal != null ? 'Edit' : 'Set a goal'}</button>
    </div>
    <span class="text-[13px] leading-[1.5] text-text1">{goalText}</span>
    {#if goalOpen}
      <form onsubmit={saveGoal} class="flex gap-2 items-center">
        <label for="goal-weight" class="sr-only">Goal weight</label>
        <input
          id="goal-weight"
          type="number"
          step="0.5"
          inputmode="decimal"
          bind:value={goalDraft}
          class="flex-1 min-w-0 h-11 px-3 rounded-xl border border-popover-border bg-bg1 text-text0 text-[16px] font-medium outline-none"
        />
        <span class="text-[13px] text-text2">{u}</span>
        <button type="submit" class="h-11 px-3.5 rounded-xl border-0 bg-blue text-on-accent text-[13px] font-semibold cursor-pointer">Save</button>
        {#if goal != null}
          <button type="button" onclick={clearGoal} class="h-11 px-3 rounded-xl border border-popover-border bg-transparent text-text1 text-[13px] font-medium cursor-pointer">Clear</button>
        {/if}
      </form>
    {/if}
  </section>

  <section aria-label="Weigh-ins" class="flex flex-col gap-1">
    <div class="flex justify-between items-baseline px-1 pt-1 pb-0.5">
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2">WEIGH-INS</span>
      <span class="text-[11px] text-text3">{entries.length} in the last year</span>
    </div>
    {#if toast}
      <div role="status" class="flex items-center gap-2.5 py-2 pr-2 pl-3 rounded-xl bg-accent-surface border border-accent-surface-border text-[13px]">
        <span class="flex-1">{toast.text}</span>
        <button type="button" onclick={undo} class="h-8 px-2.5 border-0 bg-transparent text-blue text-[13px] font-semibold cursor-pointer">Undo</button>
      </div>
    {/if}
    {#each rows as r (r.e.id)}
      <div class="flex items-center gap-2.5 min-h-[52px] py-1 pr-1 pl-3 rounded-[14px] bg-bg1 hover:bg-popover">
        <span class="flex-1 min-w-0 flex flex-col gap-0.5">
          <span class="text-[14px] font-medium">{r.val}</span>
          <span class="text-[11px] text-text2 truncate">{r.meta}</span>
        </span>
        <span class="font-mono text-[12px]" style="color: {r.dc}">{r.delta}</span>
        <button
          type="button"
          aria-label="Delete weigh-in from {format(dayDate(r.e.o), 'EEE d MMM')}"
          onclick={() => remove(r.e)}
          class="flex-none w-11 h-11 rounded-xl border-0 bg-transparent text-text3 hover:text-text1 cursor-pointer flex items-center justify-center"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg>
        </button>
      </div>
    {/each}
    {#if entries.length > (wide ? 8 : 5)}
      <button
        type="button"
        onclick={() => (showAll = !showAll)}
        class="h-10 rounded-xl border border-border bg-transparent text-text1 text-[13px] font-medium cursor-pointer"
      >{showAll ? 'Show fewer' : 'Show more weigh-ins'}</button>
    {/if}
  </section>
{/snippet}

<div class={wide ? 'grid grid-cols-[minmax(0,1fr)_340px] gap-5 items-start' : 'flex flex-col gap-3'}>
  <div class="flex flex-col gap-3 min-w-0">
    <!-- Headline -->
    <section aria-label="Current weight" class="flex justify-between items-end gap-3 px-1">
      <div class="flex flex-col gap-1">
        <span class="font-mono text-[11px] tracking-[0.14em] text-text2">{isFat ? 'BODY FAT · SMOOTHED' : 'TREND WEIGHT · TODAY'}</span>
        <span class="font-display leading-none {wide ? 'text-[64px]' : 'text-[52px]'}">{headVal}<span class="text-[18px] text-text2"> {isFat ? '%' : u}</span></span>
        <span class="text-[13px]" style="color: {chg == null ? 'var(--text2)' : chg <= 0 ? 'var(--green)' : 'var(--amber)'}">{chgText}</span>
      </div>
      <div class="flex flex-col items-end gap-2">
        <div role="radiogroup" aria-label="Units" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg2 border border-border">
          {#each ['lb', 'kg'] as const as id (id)}
            <button type="button" role="radio" aria-checked={u === id} onclick={() => { unit = id; draft = null; }} class={seg(u === id)}>{id}</button>
          {/each}
        </div>
        <button
          type="button"
          onclick={openLog}
          aria-expanded={logOpen}
          class="h-10 px-3.5 rounded-xl border-0 bg-blue text-on-accent text-[13px] font-semibold cursor-pointer"
        >+ Log weight</button>
      </div>
    </section>

    {#if logOpen}
      <form onsubmit={saveLog} class="flex flex-col gap-3 p-4 rounded-[20px] bg-accent-surface border border-accent-surface-border">
        <div class="flex justify-between items-center">
          <span class="text-[15px] font-semibold">Log a weigh-in</span>
          <button type="button" aria-label="Close" onclick={() => (logOpen = false)} class="w-9 h-9 rounded-full border-0 bg-border text-text0 cursor-pointer">×</button>
        </div>
        <div class="flex items-center gap-2">
          <button type="button" aria-label="Decrease" onclick={() => step(-0.1)} class="w-12 h-[52px] rounded-[14px] border border-accent-surface-border bg-transparent text-text0 text-[20px] cursor-pointer">−</button>
          <label for="weigh-in-value" class="sr-only">Weight in {u}</label>
          <input
            id="weigh-in-value"
            type="number"
            step="0.1"
            inputmode="decimal"
            value={draftVal}
            oninput={(e) => (draft = (e.currentTarget as HTMLInputElement).value)}
            class="flex-1 min-w-0 h-[52px] px-3 rounded-[14px] border border-accent-surface-border bg-bg0 text-text0 text-[24px] font-medium text-center outline-none"
          />
          <button type="button" aria-label="Increase" onclick={() => step(0.1)} class="w-12 h-[52px] rounded-[14px] border border-accent-surface-border bg-transparent text-text0 text-[20px] cursor-pointer">+</button>
        </div>
        <div class="flex items-center gap-2">
          <label for="weigh-in-fat" class="flex-1 text-[13px] text-text1">Body fat <span class="text-text3">(optional)</span></label>
          <input
            id="weigh-in-fat"
            type="number"
            step="0.1"
            min="2"
            max="75"
            inputmode="decimal"
            placeholder="—"
            bind:value={fatDraft}
            aria-invalid={fatInvalid}
            class="w-[96px] h-11 px-3 rounded-xl border bg-bg0 text-text0 text-[16px] font-medium text-right outline-none {fatInvalid ? 'border-red' : 'border-accent-surface-border'}"
          />
          <span class="w-4 text-[13px] text-text2">%</span>
        </div>
        {#if fatInvalid}<span class="-mt-2 text-[12px] text-red">Body fat should be between 2 and 75%.</span>{/if}
        <div role="radiogroup" aria-label="Day" class="flex gap-1.5">
          {#each [[0, 'Today'], [-1, 'Yesterday']] as const as [o, label] (o)}
            <button
              type="button"
              role="radio"
              aria-checked={logDay === o}
              onclick={() => (logDay = o)}
              class="flex-1 h-10 rounded-[11px] text-[13px] font-medium cursor-pointer border {logDay === o ? 'bg-bg0 border-blue text-text0' : 'bg-transparent border-accent-surface-border text-text1'}"
            >{label}</button>
          {/each}
        </div>
        <span class="text-[12px] text-text1">Garmin weigh-ins (an Index scale, or entered in Garmin Connect) sync on their own. Log here for any other scale. Morning, after the bathroom, before eating is most consistent.</span>
        <button type="submit" disabled={busy || fatInvalid} class="h-[46px] rounded-[14px] border-0 bg-blue text-on-accent text-[15px] font-semibold cursor-pointer disabled:opacity-60">Save {draftVal} {u}</button>
      </form>
    {/if}

    <!-- Chart -->
    <section aria-label="Weight chart" class="bg-bg2 border border-border rounded-[24px] pt-3.5 px-3.5 pb-3 flex flex-col gap-2.5">
      <div class="flex justify-between items-center gap-2 flex-wrap">
        <div role="tablist" aria-label="Metric" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
          {#each [['weight', 'Weight'], ['fat', 'Body fat']] as const as [id, label] (id)}
            <button type="button" role="tab" aria-selected={metric === id} onclick={() => { metric = id; hover = null; }} class={seg(metric === id)}>{label}</button>
          {/each}
        </div>
        <div role="tablist" aria-label="Range" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
          {#each RANGES as r (r.days)}
            <button type="button" role="tab" aria-selected={range === r.days} onclick={() => { range = r.days; hover = null; }} class={seg(range === r.days)}>{r.label}</button>
          {/each}
        </div>
      </div>
      <span aria-live="polite" class="font-mono text-[11px] {hover ? 'text-text0' : 'text-text2'}">{readout}</span>
      {#if loading && !data}
        <div class="rounded-2xl bg-bg1 animate-pulse" style="height: {chartH}px" aria-label="Loading weight"></div>
      {:else if !inR.length}
        <div class="flex items-center justify-center text-center px-6 text-[13px] leading-[1.5] text-text2" style="height: {chartH}px">
          {#if isFat}
            No body-fat readings{hasEntries ? ' in this range' : ''}. Add one when you log a weigh-in, or sync a smart scale such as Garmin Index.
          {:else if hasEntries}
            No weigh-ins in the last {range} days. Pick a longer range or log one.
          {:else}
            No weigh-ins yet. Log one, or connect a Garmin with an Index scale.
          {/if}
        </div>
      {:else}
        <div class="relative" style="height: {chartH}px">
          <svg width="100%" height={chartH} viewBox="0 0 1000 200" preserveAspectRatio="none" role="img" aria-label="{isFat ? 'Body fat' : 'Weight'} over the last {range} days: weigh-ins as dots with a smoothed trend line{showGoal ? ' and a goal line' : ''}" class="block">
            {#each grid as g (g.v)}
              <line x1="0" y1={g.y.toFixed(1)} x2="1000" y2={g.y.toFixed(1)} stroke="#232327" vector-effect="non-scaling-stroke"></line>
            {/each}
            {#if showGoal && goal != null}
              <line x1="0" y1={Y(K(goal)).toFixed(1)} x2="1000" y2={Y(K(goal)).toFixed(1)} stroke="var(--green)" stroke-opacity="0.7" stroke-dasharray="6 5" vector-effect="non-scaling-stroke"></line>
            {/if}
            {#if proj}
              <polyline points={proj} fill="none" stroke="var(--blue)" stroke-opacity="0.55" stroke-width="1.6" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"></polyline>
            {/if}
            {#each dots as p (p.e.id)}
              <line x1={p.x.toFixed(1)} y1={p.y.toFixed(1)} x2={p.x.toFixed(1)} y2={p.y.toFixed(1)} stroke={p.c} stroke-opacity={hover?.id === p.e.id ? 1 : 0.55} stroke-width={range > 180 ? 4 : 6} stroke-linecap="round" vector-effect="non-scaling-stroke"></line>
            {/each}
            <polyline points={line} fill="none" stroke="var(--blue)" stroke-width="2.2" stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>
          </svg>
          <div aria-hidden="true" class="absolute left-0.5 top-0 bottom-0 pointer-events-none">
            {#each grid as g (g.v)}
              <span class="absolute left-0 -translate-y-[110%] font-mono text-[9px] text-text3" style="top: {(g.y / 2).toFixed(1)}%">{g.label}</span>
            {/each}
          </div>
          {#if showGoal && goal != null}
            <span aria-hidden="true" class="absolute right-1 -translate-y-[120%] font-mono text-[9px] text-green" style="top: {(Y(K(goal)) / 2).toFixed(1)}%">GOAL {r1(K(goal))}</span>
          {/if}
          {#if hover}
            {@const hv = isFat ? (hover.body_fat_pct ?? 0) : K(hover.weight_kg)}
            <span aria-hidden="true" class="absolute top-0 bottom-0 w-px bg-[rgba(237,235,230,0.4)] pointer-events-none" style="left: {(X(hover.o) / 10).toFixed(2)}%"></span>
            <span aria-hidden="true" class="absolute w-2.5 h-2.5 -ml-[5px] -mt-[5px] rounded-full bg-text0 pointer-events-none shadow-[0_0_0_3px_var(--bg2)]" style="left: {(X(hover.o) / 10).toFixed(2)}%; top: {(Y(hv) / 2).toFixed(2)}%"></span>
          {/if}
          <div role="presentation" onpointerdown={pMove} onpointermove={pMove} onpointerleave={() => (hover = null)} class="absolute inset-0 cursor-crosshair touch-none"></div>
        </div>
        <div aria-hidden="true" class="relative h-3.5 font-mono text-[10px] text-text3">
          {#each ticks as t (t.o)}
            <span class="absolute top-0 whitespace-nowrap" style="left: {(X(t.o) / 10).toFixed(2)}%; transform: translateX({t.shift})">{t.label}</span>
          {/each}
          {#if xEnd}<span class="absolute top-0 right-0 text-blue">PROJECTED</span>{/if}
        </div>
        <div class="flex gap-3.5 flex-wrap text-[11px] text-text2">
          <span class="flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-text1"></span>Weigh-in</span>
          <span class="flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-amber"></span>Logged here</span>
          <span class="flex items-center gap-1.5"><span class="w-3.5 h-0.5 bg-blue"></span>Trend (smoothed)</span>
          {#if showGoal}<span class="flex items-center gap-1.5"><span class="w-3.5 h-0 border-t-2 border-dashed border-green"></span>Goal</span>{/if}
        </div>
      {/if}
    </section>

    <div class="flex gap-3 items-start px-4 py-3.5 rounded-[18px] bg-bg1 border border-dashed border-popover-border">
      <span class="font-mono text-[10px] tracking-[0.12em] text-blue pt-0.5">COACH</span>
      <span class="text-[13px] leading-[1.5] text-[#CFCCC4]">{coach}</span>
    </div>

    {#if !wide}{@render sideCol()}{/if}
  </div>

  {#if wide}
    <div class="flex flex-col gap-3 min-w-0">{@render sideCol()}</div>
  {/if}
</div>
