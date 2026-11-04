<script lang="ts" module>
  import type { WorkoutPlanLink as Link } from '$lib/types/linking';
  import type { Interval as Step } from '$lib/types/training';

  /** Per-workout cache: the detail pane can remount this panel while it refreshes the
   * workout, so a remount shows the last data at once and only refetches after 30 s. */
  const cache = new Map<string, { at: number; data: Link | null; structure: Step[] }>();
  const FRESH_MS = 30_000;

  /** Drop cached links (call after linking / unlinking elsewhere, e.g. on the Plan page). */
  export function invalidateWorkoutPlanLinks(): void {
    cache.clear();
  }
</script>

<script lang="ts">
  /**
   * Planned session for a recorded workout (design: PWorkoutLink).
   * Linked: the session it completes (auto-matched or linked by hand), planned vs actual
   * (blocks overlaid on the power or heart-rate trace, and a small table), Change session /
   * Unlink. Not linked: why, a one-tap "Looks like a match" suggestion, and a session picker.
   */
  import { untrack } from 'svelte';
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { confirm } from '$lib/confirm';
  import type { ActivityStreams } from '$lib/services/activityService';
  import type { Interval } from '$lib/types/training';
  import type { PlanCandidate, PlanSummary, WorkoutPlanLink } from '$lib/types/linking';
  import {
    comparisonRows,
    dayShort,
    plannedBlocks,
    sessionMeta,
    traceLine,
    unlinkConfirmText,
    unlinkedText
  } from '$lib/utils/workoutLinking';
  import WorkoutSessionPicker from './WorkoutSessionPicker.svelte';

  let {
    workoutId,
    streams = null,
    ftp: ftpProp = 0,
    onchange
  }: {
    workoutId: string;
    streams?: ActivityStreams | null;
    ftp?: number;
    /** Called after a link change (e.g. to refresh the plan). */
    onchange?: () => void;
  } = $props();

  /** FTP for the power trace scale and time at threshold (the profile when not passed). */
  const ftp = $derived(ftpProp || Number(athleteStore.profile?.ftp_watts) || 0);
  const cached = untrack(() => cache.get(workoutId));
  let data = $state<WorkoutPlanLink | null>(cached?.data ?? null);
  let structure = $state<Interval[]>(cached?.structure ?? []);
  let loading = $state(!cached);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let picking = $state(false);
  let toast = $state<{ text: string; undo: (() => Promise<void>) | null } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | null = null;
  let mode = $state<'power' | 'hr'>('power');

  async function load(id: string, force = false) {
    const hit = cache.get(id);
    if (hit) {
      data = hit.data;
      structure = hit.structure;
      loading = false;
      if (!force && Date.now() - hit.at < FRESH_MS) return;
    } else {
      data = null;
      structure = [];
      loading = true;
    }
    error = null;
    const res = await api.getWorkoutPlanLink(id);
    if (id !== workoutId) return; // a newer workout was opened meanwhile
    let steps: Interval[] = [];
    if (res?.linked) {
      // The plan summary has no intervals; read them from the plan list for that day.
      const day = res.linked.date;
      const rows = await api.getWorkouts(day, day).catch(() => []);
      steps = rows.find((r) => r.id === res.linked?.id)?.structure ?? [];
    }
    if (res) cache.set(id, { at: Date.now(), data: res, structure: steps });
    if (id !== workoutId) return;
    data = res;
    structure = steps;
    loading = false;
  }

  $effect(() => {
    const id = workoutId;
    untrack(() => void load(id));
  });

  function flash(text: string, undo: (() => Promise<void>) | null) {
    toast = { text, undo };
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 6000);
  }

  async function run(fn: () => Promise<boolean>) {
    if (busy) return;
    busy = true;
    error = null;
    try {
      if (await fn()) {
        await load(workoutId, true);
        onchange?.();
      }
    } finally {
      busy = false;
    }
  }

  async function linkTo(planId: string, title: string, previous: PlanSummary | null, wasDone = false) {
    await run(async () => {
      // Changing session: this workout already completes another one, so move the link.
      const res = await api.linkWorkoutToPlan(planId, workoutId, Boolean(previous));
      if (!res.ok) {
        error = 'conflict' in res ? `Already linked to ${res.conflict.title}.` : "Couldn't link the workout. Try again.";
        return false;
      }
      picking = false;
      flash(`Linked to ${title}.`, async () => {
        if (previous) await api.linkWorkoutToPlan(previous.id, workoutId, true);
        // Undo: keep the workout suggestible, and a session done by hand stays done.
        else await api.unlinkPlanWorkout(planId, { dismiss: false, done: wasDone });
        await load(workoutId, true);
        onchange?.();
      });
      return true;
    });
  }

  function pick(c: PlanCandidate) {
    void linkTo(c.id, c.title, data?.linked ?? null, !c.has_other_workout && c.completed);
  }

  async function dismiss(c: PlanCandidate) {
    await run(async () => {
      const ok = await api.dismissPlanSuggestion(c.id, workoutId);
      if (!ok) error = "Couldn't update. Try again.";
      return Boolean(ok);
    });
  }

  async function unlink() {
    const linked = data?.linked;
    if (!linked) return;
    const ok = await confirm({
      title: `Unlink from ${linked.title}?`,
      message: unlinkConfirmText(linked, linked.link_source),
      confirmText: 'Unlink',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (!ok) return;
    await run(async () => {
      const res = await api.unlinkPlanWorkout(linked.id);
      if (!res) {
        error = "Couldn't unlink. Try again.";
        return false;
      }
      flash(`Unlinked from ${linked.title}.`, async () => {
        await api.linkWorkoutToPlan(linked.id, workoutId, true);
        await load(workoutId, true);
        onchange?.();
      });
      return true;
    });
  }

  // --- chart + table ---------------------------------------------------------------------
  const W = 320;
  const H = 120;
  const ts = $derived(streams?.time_series ?? {});
  const step = $derived(streams?.resolution_seconds || 1);
  const hasPower = $derived((ts.watts?.length ?? 0) > 1 && ftp > 0);
  const hasHr = $derived((ts.heartrate?.length ?? 0) > 1);
  $effect(() => {
    if (mode === 'power' && !hasPower && hasHr) mode = 'hr';
  });
  const modes = $derived.by(() => {
    const out: ['power' | 'hr', string][] = [];
    if (hasPower) out.push(['power', 'Power']);
    if (hasHr) out.push(['hr', 'HR']);
    return out;
  });
  const planMin = $derived(structure.reduce((s, i) => s + (i.duration_minutes || 0), 0) || data?.linked?.duration_minutes || 0);
  const actualMin = $derived((data?.workout.duration_seconds ?? 0) / 60);
  const spanMin = $derived(Math.max(planMin, actualMin, 1));
  const blocks = $derived(structure.length ? plannedBlocks(structure, spanMin, W, H - 10) : []);
  const line = $derived.by(() => {
    if (mode === 'power' && hasPower) return traceLine(ts.watts, ts.time, step, spanMin, W, H - 10, ftp * 1.3);
    if (hasHr) {
      const max = Math.max(...(ts.heartrate ?? [0]).filter((v) => Number.isFinite(v)), 1);
      return traceLine(ts.heartrate, ts.time, step, spanMin, W, H - 10, max * 1.05);
    }
    return '';
  });
  const showChart = $derived(blocks.length > 0 || line !== '');
  const cmp = $derived(
    data?.linked
      ? comparisonRows(
          { duration_minutes: data.linked.duration_minutes, projected_tss: data.linked.projected_tss, structure },
          { duration_seconds: data.workout.duration_seconds, tss: data.workout.tss },
          hasPower ? { watts: ts.watts, time: ts.time, step, ftp } : undefined
        )
      : []
  );
  const toneClass = { good: 'text-green', warn: 'text-amber', neutral: 'text-text0' } as const;
  const sug = $derived(data?.suggestion ?? null);
  const pickTitle = $derived(data?.linked ? 'Change session' : 'Link to a session');
  const dateLabel = $derived(data?.workout.started_at ? dayShort(data.workout.started_at) : '');
</script>

{#if loading && !data}
  <div aria-hidden="true" class="h-[120px] rounded-[24px] bg-bg2 border border-border animate-pulse"></div>
{:else if data}
  <section aria-label="Planned session" class="bg-bg2 border border-border rounded-[24px] p-4 flex flex-col gap-3">
    {#if data.linked}
      {@const p = data.linked}
      <div class="flex justify-between items-center gap-2">
        <span class="font-mono text-[11px] tracking-[0.14em] text-green">✓ PLANNED SESSION</span>
        <span
          class="font-mono text-[10px] tracking-[0.1em] px-2 py-1 rounded-md {p.link_source === 'auto'
            ? 'bg-bg3 text-text1'
            : 'bg-accent-surface text-blue'}">{p.link_source === 'auto' ? 'AUTO-MATCHED' : 'LINKED BY YOU'}</span
        >
      </div>
      <a href="/plan?session={encodeURIComponent(p.id)}&date={encodeURIComponent(p.date)}" class="flex items-center gap-3 p-3 rounded-2xl bg-bg1 border border-rail-border no-underline text-text0">
        <span aria-hidden="true" class="shrink-0 w-1 h-9 rounded-sm bg-blue"></span>
        <span class="flex-1 min-w-0 flex flex-col gap-0.5">
          <span class="text-[15px] font-medium truncate">{p.title}</span>
          <span class="text-[12px] text-text2">{sessionMeta(p)}</span>
        </span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text3"><path d="m9 6 6 6-6 6"></path></svg>
      </a>

      {#if showChart || cmp.length}
        <div class="flex justify-between items-center gap-2">
          <span class="text-[13px] font-medium">Planned vs actual</span>
          {#if modes.length > 1}
            <div role="tablist" aria-label="Trace" class="flex gap-0.5 p-[3px] rounded-[10px] bg-bg1 border border-border">
              {#each modes as [id, label] (id)}
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === id}
                  class="h-7 px-2.5 border-0 rounded-[7px] text-[12px] font-medium cursor-pointer {mode === id ? 'bg-border text-text0' : 'bg-transparent text-text2'}"
                  onclick={() => (mode = id)}
                >{label}</button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
      {#if showChart}
        <svg width="100%" height={H} viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="Planned blocks with the recorded {mode === 'power' ? 'power' : 'heart rate'}" class="block">
          <line x1="0" y1={H - 10} x2={W} y2={H - 10} stroke="var(--border)" vector-effect="non-scaling-stroke"></line>
          {#each blocks as b, i (i)}
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill={b.color} fill-opacity="0.22" stroke={b.color} stroke-opacity="0.5" stroke-dasharray="3 2" vector-effect="non-scaling-stroke"></rect>
          {/each}
          {#if line}
            <polyline points={line} fill="none" stroke={mode === 'power' ? 'var(--blue)' : 'var(--red)'} stroke-width="1.8" stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>
          {/if}
        </svg>
        <div class="flex gap-3.5 text-[11px] text-text2">
          {#if blocks.length}
            <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3 h-2 rounded-sm border border-dashed border-text1 bg-text1/15"></span>Planned blocks</span>
          {/if}
          {#if line}
            <span class="flex items-center gap-1.5"><span aria-hidden="true" class="w-3.5 h-0.5 {mode === 'power' ? 'bg-blue' : 'bg-red'}"></span>{mode === 'power' ? 'Actual power' : 'Actual heart rate'}</span>
          {/if}
        </div>
      {/if}
      {#if cmp.length}
        <table class="w-full border-collapse text-[13px]">
          <thead>
            <tr class="font-mono text-[10px] tracking-[0.1em] text-text2 text-left">
              <th class="py-1.5 font-medium"><span class="sr-only">Measure</span></th>
              <th class="py-1.5 font-medium text-right">PLANNED</th>
              <th class="py-1.5 font-medium text-right">ACTUAL</th>
            </tr>
          </thead>
          <tbody>
            {#each cmp as c (c.k)}
              <tr class="border-t border-border">
                <td class="py-2.5 text-text1">{c.k}</td>
                <td class="py-2.5 text-right font-mono">{c.p}</td>
                <td class="py-2.5 text-right font-mono {toneClass[c.tone]}">{c.a}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      <div class="grid grid-cols-2 gap-2">
        <button type="button" disabled={busy} class="h-11 rounded-[13px] border border-popover-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50" onclick={() => (picking = true)}>Change session</button>
        <button type="button" disabled={busy} class="h-11 rounded-[13px] border border-red/40 bg-transparent text-red text-[14px] font-medium cursor-pointer disabled:opacity-50" onclick={unlink}>Unlink</button>
      </div>
    {:else}
      <span class="font-mono text-[11px] tracking-[0.14em] text-text2">PLANNED SESSION</span>
      <span class="text-[14px] leading-normal text-text1">{unlinkedText(Boolean(sug))}</span>
      {#if sug}
        <div class="flex flex-col gap-2.5 p-3.5 rounded-2xl bg-accent-surface border border-accent-surface-border">
          <span class="font-mono text-[10px] tracking-[0.14em] text-blue">LOOKS LIKE A MATCH</span>
          <span class="text-[15px] leading-snug"><strong class="font-semibold">{sug.title}</strong> · {sessionMeta(sug)} ({sug.fit.reason}) — link it?</span>
          <div class="grid grid-cols-2 gap-2">
            <button type="button" disabled={busy} class="h-11 rounded-xl border-0 bg-blue text-on-accent text-[14px] font-semibold cursor-pointer disabled:opacity-50" onclick={() => linkTo(sug.id, sug.title, null, sug.completed)}>Link it</button>
            <button type="button" disabled={busy} class="h-11 rounded-xl border border-accent-surface-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50" onclick={() => dismiss(sug)}>Not this one</button>
          </div>
        </div>
      {/if}
      <button type="button" disabled={busy} class="h-[46px] rounded-[13px] border border-popover-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50" onclick={() => (picking = true)}>Link to a planned session…</button>
    {/if}
    {#if error}
      <p role="alert" class="m-0 text-[13px] text-red">{error}</p>
    {/if}
  </section>

  {#if toast}
    <div role="status" class="fixed left-4 right-4 bottom-24 z-[65] mx-auto max-w-[480px] flex items-center gap-2.5 min-h-12 pl-4 pr-2 rounded-[14px] bg-border shadow-[0_10px_30px_rgba(0,0,0,0.45)] text-[14px] text-text0">
      <span class="flex-1">{toast.text}</span>
      {#if toast.undo}
        <button
          type="button"
          class="h-10 px-3 border-0 bg-transparent text-blue text-[14px] font-semibold cursor-pointer"
          onclick={async () => {
            const u = toast?.undo;
            toast = null;
            if (u) await u();
          }}
        >Undo</button>
      {/if}
    </div>
  {/if}

  {#if picking}
    <WorkoutSessionPicker
      title={pickTitle}
      {dateLabel}
      rows={data.candidates}
      workoutSport={data.workout.sport}
      {busy}
      onpick={pick}
      onclose={() => (picking = false)}
    />
  {/if}
{/if}
