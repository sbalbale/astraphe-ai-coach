<script lang="ts">
  /**
   * Planned session ↔ recorded workout, on the Plan sheet (phone) and Plan inspector (wide).
   * Design: Plan · link a workout. States:
   *  - linked        ✓ COMPLETED card, auto/manual tag, TSS and duration vs plan,
   *                  Open in training log · Change workout · Unlink
   *  - not done      "Looks like a match" suggestion (Link it / Not this one), then
   *                  Mark as done · Link a workout…; future days also explain auto-linking
   *  - done by hand  ✓ DONE · NO WORKOUT, Link a workout… · Mark not done
   * Every change refreshes the plan (`onchanged`) and offers Undo where it can be undone.
   */
  import { onDestroy } from 'svelte';
  import { navTo } from '$lib/nav';
  import { api } from '$lib/api';
  import type { Workout } from '$lib/types/training';
  import type { WorkoutCandidate } from '$lib/types/linking';
  import {
    dayNote,
    dayShort,
    hm,
    linkSourceLabel,
    sessionLinkState,
    suggestionWhy,
    sportBadge,
    sportWord,
    tssVsPlan,
    workoutMeta
  } from '$lib/utils/linking';
  import WorkoutPicker from './WorkoutPicker.svelte';
  import { invalidateWorkoutPlanLinks } from './WorkoutPlanPanel.svelte';
  import PlanUnlinkConfirm from './PlanUnlinkConfirm.svelte';

  let {
    plan,
    todayIso,
    wide = false,
    onsetdone,
    onchanged
  }: {
    plan: Workout;
    todayIso: string;
    wide?: boolean;
    /** Mark done / not done without a workout; resolves false on failure. */
    onsetdone: (done: boolean) => Promise<boolean>;
    /** Reload the plan after a link change. */
    onchanged: () => Promise<void>;
  } = $props();

  const linkState = $derived(sessionLinkState(plan, todayIso));
  const w = $derived(plan.linked_workout ?? null);
  const plannedMin = $derived(Number(plan.duration_minutes) || 0);
  const plannedTss = $derived(Number(plan.projected_tss) || 0);
  const tss = $derived(tssVsPlan(w?.tss, plannedTss));

  let candidates = $state<WorkoutCandidate[] | null>(null);
  let suggestion = $state<WorkoutCandidate | null>(null);
  let loadedFor = '';
  let busy = $state(false);
  let error = $state<string | null>(null);
  let sheet = $state<'none' | 'pick' | 'unlink'>('none');
  let toast = $state<{ message: string; undo?: () => Promise<void> } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | null = null;

  async function loadCandidates() {
    const id = plan.id;
    const res = await api.getPlanLinkCandidates(id);
    if (id !== plan.id) return; // another session was selected meanwhile
    candidates = res?.candidates ?? [];
    suggestion = res?.suggestion ?? null;
  }

  // Suggestion for a session that isn't done yet (today or earlier): reload when the
  // session or its link changes.
  $effect(() => {
    const key = `${plan.id}|${plan.completed}|${plan.completed_workout_id ?? ''}`;
    if (key === loadedFor) return;
    loadedFor = key;
    suggestion = null;
    candidates = null;
    if (linkState === 'missed' || linkState === 'today') void loadCandidates();
  });

  function showToast(message: string, undo?: () => Promise<void>) {
    toast = { message, undo };
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 6000);
  }
  onDestroy(() => {
    if (toastTimer) clearTimeout(toastTimer);
  });

  async function run(fn: () => Promise<boolean | void>): Promise<boolean> {
    busy = true;
    error = null;
    try {
      const ok = await fn();
      if (ok === false) {
        error = "Couldn't update the session. Try again.";
        return false;
      }
      invalidateWorkoutPlanLinks();
      await onchanged();
      return true;
    } finally {
      busy = false;
    }
  }

  /** Put the link back the way it was before a change (for Undo). */
  function restoreTo(prev: { workoutId: string | null; completed: boolean }): () => Promise<void> {
    const planId = plan.id;
    const setDone = onsetdone;
    return async () => {
      await run(async () => {
        if (prev.workoutId) {
          const r = await api.linkWorkoutToPlan(planId, prev.workoutId, true);
          return r.ok;
        }
        // Undo of a link: back to how it was (done by hand or not), without dismissing the workout.
        if (plan.id === planId && plan.completed_workout_id) {
          return !!(await api.unlinkPlanWorkout(planId, { dismiss: false, done: prev.completed }));
        }
        return setDone(prev.completed);
      });
      toast = null;
    };
  }

  async function link(c: WorkoutCandidate, move: boolean) {
    const prev = { workoutId: plan.completed_workout_id ?? null, completed: !!plan.completed };
    busy = true;
    error = null;
    try {
      const r = await api.linkWorkoutToPlan(plan.id, c.id, move);
      if (!r.ok) {
        error =
          'conflict' in r
            ? `This workout already completes ${r.conflict.title || 'another session'}. Pick it again to move the link.`
            : "Couldn't link the workout. Try again.";
        if ('conflict' in r) await loadCandidates();
        return;
      }
      sheet = 'none';
      invalidateWorkoutPlanLinks();
      await onchanged();
      showToast(`Linked ${c.title}.`, restoreTo(prev));
    } finally {
      busy = false;
    }
  }

  async function openPicker() {
    sheet = 'pick';
    error = null;
    await loadCandidates();
  }

  async function dismissSuggestion() {
    const s = suggestion;
    if (!s) return;
    suggestion = null;
    const ok = await api.dismissPlanSuggestion(plan.id, s.id);
    if (!ok) error = "Couldn't update the session. Try again.";
    else showToast(`Won't suggest ${s.title} for this session again.`);
    await loadCandidates();
  }

  async function unlink() {
    const prevId = plan.completed_workout_id ?? null;
    const title = w?.title ?? 'workout';
    const ok = await run(async () => !!(await api.unlinkPlanWorkout(plan.id)));
    sheet = 'none';
    if (ok) {
      showToast(`Unlinked. ${plan.title || 'The session'} is not done.`, prevId ? restoreTo({ workoutId: prevId, completed: true }) : undefined);
    } else {
      error = `Couldn't unlink ${title}. Try again.`;
    }
  }

  async function setDone(done: boolean) {
    const ok = await run(() => onsetdone(done));
    if (ok) showToast(done ? 'Marked done without a workout.' : 'Marked not done.', restoreTo({ workoutId: null, completed: !done }));
  }

  const btn =
    'h-11 rounded-[13px] border border-popover-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50 hover:border-text3';
</script>

<section aria-label="Completion" class="flex flex-col gap-2.5 pt-3.5 border-t border-border">
  {#if linkState === 'linked' && w}
    <div class="flex justify-between items-center">
      <span class="font-mono text-[11px] tracking-[0.14em] text-green">✓ COMPLETED</span>
      <span class="font-mono text-[10px] tracking-[0.1em] px-2 py-1 rounded-md {plan.link_source === 'auto' ? 'bg-bg3 text-text1' : 'bg-accent-surface text-blue'}">{linkSourceLabel(plan.link_source)}</span>
    </div>
    <button
      type="button"
      class="flex items-center gap-3 p-3 rounded-2xl bg-bg1 border border-rail-border text-left text-text0 cursor-pointer hover:border-text3"
      onclick={() => navTo(`/training?workout_id=${encodeURIComponent(w.id)}`)}
    >
      <span aria-hidden="true" class="shrink-0 w-10 h-10 rounded-xl bg-accent-surface text-blue flex items-center justify-center font-mono text-[10px]">{sportBadge(w.sport)}</span>
      <span class="flex-1 min-w-0 flex flex-col gap-0.5">
        <span class="text-[14px] font-medium truncate">{w.title}</span>
        <span class="text-[12px] text-text2">{workoutMeta(w)}</span>
      </span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" class="text-text3 shrink-0"><path d="m9 6 6 6-6 6"></path></svg>
    </button>
    <div class="grid grid-cols-2 gap-2">
      <div class="px-3 py-2.5 rounded-[14px] bg-bg1 flex flex-col gap-1.5">
        <span class="text-[11px] text-text2">TSS vs plan</span>
        <span class="text-[16px] font-medium">{tss.label}</span>
        <span aria-hidden="true" class="block h-1 rounded-sm bg-border"><span class="block h-1 rounded-sm {tss.onTarget ? 'bg-green' : 'bg-amber'}" style="width: {tss.width}%"></span></span>
      </div>
      <div class="px-3 py-2.5 rounded-[14px] bg-bg1 flex flex-col gap-1.5">
        <span class="text-[11px] text-text2">Duration · actual / plan</span>
        <span class="text-[16px] font-medium">{hm(w.duration_seconds / 60)} / {plannedMin ? hm(plannedMin) : '—'}</span>
        <span class="text-[11px] text-text2">{dayNote(w.started_at, plan.date)}</span>
      </div>
    </div>
    <button type="button" class="{btn} bg-bg1" onclick={() => navTo(`/training?workout_id=${encodeURIComponent(w.id)}`)}>Open in training log</button>
    <div class="grid grid-cols-2 gap-2">
      <button type="button" class={btn} disabled={busy} onclick={openPicker}>Change workout</button>
      <button type="button" class="{btn} !border-red/40 !text-red" disabled={busy} onclick={() => (sheet = 'unlink')}>Unlink</button>
    </div>
  {:else if linkState === 'linked' && !w}
    <span class="font-mono text-[11px] tracking-[0.14em] text-green">✓ COMPLETED</span>
    <span class="text-[13px] leading-normal text-text1">Linked to a recorded workout, but its details couldn't be loaded right now.</span>
    <div class="grid grid-cols-2 gap-2">
      <button type="button" class={btn} disabled={busy} onclick={openPicker}>Change workout</button>
      <button type="button" class="{btn} !border-red/40 !text-red" disabled={busy} onclick={unlink}>Unlink</button>
    </div>
  {:else if linkState === 'mark'}
    <span class="font-mono text-[11px] tracking-[0.14em] text-green">✓ DONE · NO WORKOUT</span>
    <span class="text-[13px] leading-normal text-text1">
      You marked this done by hand. It counts as planned TSS{plannedTss ? ` (${plannedTss})` : ''} until you link a recording.
    </span>
    <div class="grid grid-cols-2 gap-2">
      <button type="button" class={btn} disabled={busy} onclick={openPicker}>Link a workout…</button>
      <button type="button" class={btn} disabled={busy} onclick={() => setDone(false)}>Mark not done</button>
    </div>
  {:else}
    {#if suggestion}
      <div class="flex flex-col gap-2.5 p-3.5 rounded-2xl bg-accent-surface border border-accent-surface-border">
        <span class="font-mono text-[10px] tracking-[0.14em] text-blue">LOOKS LIKE A MATCH</span>
        <span class="text-[15px] leading-snug">
          <strong class="font-semibold">{suggestion.title}</strong> · {workoutMeta(suggestion)} — link it?
        </span>
        <span class="text-[12px] text-text1">{suggestionWhy(suggestion.fit)}</span>
        <div class="grid grid-cols-2 gap-2">
          <button type="button" disabled={busy} class="h-11 rounded-xl border-0 bg-blue text-on-accent text-[14px] font-semibold cursor-pointer disabled:opacity-50" onclick={() => suggestion && link(suggestion, false)}>Link it</button>
          <button type="button" disabled={busy} class="h-11 rounded-xl border border-accent-surface-border bg-transparent text-text0 text-[14px] font-medium cursor-pointer disabled:opacity-50" onclick={dismissSuggestion}>Not this one</button>
        </div>
      </div>
    {:else if linkState === 'missed' && candidates !== null}
      <span class="text-[13px] text-text1">Nothing recorded for this session yet.</span>
    {/if}
    {#if linkState === 'future' || (linkState === 'today' && !suggestion)}
      <span class="text-[13px] leading-normal text-text1">
        When a {sportWord(plan.sport)}{plannedMin ? ` of about ${hm(plannedMin)}` : ''} syncs on {linkState === 'today' ? 'today' : dayShort(plan.date)}, it's linked automatically and this session is marked done.
      </span>
    {/if}
    <div class="grid grid-cols-2 gap-2">
      <button type="button" class={btn} disabled={busy} onclick={() => setDone(true)}>Mark as done</button>
      <button type="button" class={btn} disabled={busy} onclick={openPicker}>Link a workout…</button>
    </div>
  {/if}

  {#if error && sheet === 'none'}
    <p role="alert" class="m-0 text-[13px] text-red">{error}</p>
  {/if}
  {#if toast}
    <div role="status" class="flex items-center gap-2.5 min-h-12 pl-4 pr-2 rounded-[14px] bg-border text-[14px]">
      <span class="flex-1">{toast.message}</span>
      {#if toast.undo}
        <button type="button" disabled={busy} class="h-10 px-3 border-0 bg-transparent text-blue text-[14px] font-semibold cursor-pointer disabled:opacity-50" onclick={toast.undo}>Undo</button>
      {:else}
        <button type="button" aria-label="Dismiss" class="h-10 px-3 border-0 bg-transparent text-text2 cursor-pointer" onclick={() => (toast = null)}>×</button>
      {/if}
    </div>
  {/if}
</section>

{#if sheet === 'pick'}
  <WorkoutPicker
    title={linkState === 'linked' ? 'Change workout' : 'Link a workout'}
    subtitle="For {plan.title || 'this session'} · {dayShort(plan.date)}"
    {candidates}
    planSport={plan.sport}
    {wide}
    {busy}
    {error}
    onclose={() => {
      sheet = 'none';
      error = null;
    }}
    onpick={link}
  />
{:else if sheet === 'unlink' && w}
  <PlanUnlinkConfirm workoutTitle={w.title} source={plan.link_source} {wide} {busy} oncancel={() => (sheet = 'none')} onconfirm={unlink} />
{/if}
